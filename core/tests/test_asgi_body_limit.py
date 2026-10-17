import asyncio

from django.test import SimpleTestCase, override_settings

from core.middleware import BodySizeLimitASGI


class _RecordingApp:
    def __init__(self):
        self.calls = 0
        self.scope_type = None
        self.body = None

    async def __call__(self, scope, receive, send):
        self.calls += 1
        self.scope_type = scope["type"]
        if scope["type"] != "http":
            return
        message = await receive()
        self.body = message.get("body")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _run(scope, messages, app):
    pending = list(messages)
    sent = []

    async def receive():
        if pending:
            return pending.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(BodySizeLimitASGI(app)(scope, receive, send))
    return sent


def _http_scope(headers=None):
    return {"type": "http", "headers": headers or []}


class BodySizeLimitASGITests(SimpleTestCase):
    def test_a_body_within_the_limit_reaches_the_app(self):
        app = _RecordingApp()
        messages = [{"type": "http.request", "body": b"hello", "more_body": False}]
        with override_settings(MAX_REQUEST_BODY_BYTES=100):
            sent = _run(_http_scope(), messages, app)
        self.assertEqual(app.calls, 1)
        self.assertEqual(app.body, b"hello")
        self.assertEqual(sent[0]["status"], 200)

    def test_a_declared_content_length_over_the_limit_is_rejected_early(self):
        app = _RecordingApp()
        scope = _http_scope([(b"content-length", b"1000")])
        with override_settings(MAX_REQUEST_BODY_BYTES=100):
            sent = _run(scope, [], app)
        self.assertEqual(app.calls, 0)
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(sent[1]["type"], "http.response.body")
        self.assertIn(b"request_too_large", sent[1]["body"])

    def test_a_chunked_body_over_the_limit_is_rejected(self):
        app = _RecordingApp()
        messages = [
            {"type": "http.request", "body": b"x" * 60, "more_body": True},
            {"type": "http.request", "body": b"y" * 60, "more_body": False},
        ]
        with override_settings(MAX_REQUEST_BODY_BYTES=100):
            sent = _run(_http_scope(), messages, app)
        self.assertEqual(app.calls, 0)
        self.assertEqual(sent[0]["status"], 413)

    def test_a_body_that_crosses_the_limit_is_never_replayed(self):
        app = _RecordingApp()
        messages = [
            {"type": "http.request", "body": b"x" * 100, "more_body": True},
            {"type": "http.request", "body": b"y" * 100, "more_body": False},
        ]
        with override_settings(MAX_REQUEST_BODY_BYTES=150):
            sent = _run(_http_scope(), messages, app)
        self.assertEqual(app.calls, 0)
        self.assertEqual(sent[0]["status"], 413)

    def test_a_client_disconnect_during_the_body_is_ignored(self):
        app = _RecordingApp()
        messages = [
            {"type": "http.request", "body": b"hello", "more_body": True},
            {"type": "http.disconnect"},
        ]
        with override_settings(MAX_REQUEST_BODY_BYTES=100):
            sent = _run(_http_scope(), messages, app)
        self.assertEqual(app.calls, 0)
        self.assertEqual(sent, [])

    def test_non_http_scopes_pass_through(self):
        app = _RecordingApp()
        sent = _run({"type": "websocket"}, [], app)
        self.assertEqual(app.calls, 1)
        self.assertEqual(app.scope_type, "websocket")
        self.assertEqual(sent, [])
