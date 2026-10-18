import io
import json
import logging
import re

from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.logs import JsonFormatter, request_id_var, user_id_var
from core.tests.factories import UserFactory

HEADER = "X-Request-ID"
HEX_ID = re.compile(r"[0-9a-f]{32}")
ALLOWED_ORIGIN = "https://frontend.example.com"
TRACE_URLCONF = "core.tests.urls_logging"


def _client_for(user, **defaults):
    client = APIClient(**defaults)
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class LogCapture:
    def __init__(self):
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(JsonFormatter())

    def __enter__(self):
        logging.getLogger().addHandler(self.handler)
        return self

    def __exit__(self, *exc_info):
        logging.getLogger().removeHandler(self.handler)

    @property
    def raw(self):
        return self.stream.getvalue()

    @property
    def lines(self):
        return [json.loads(line) for line in self.raw.splitlines() if line]

    def access(self):
        return [line for line in self.lines if line["logger"] == "core.access"]


class RequestIdHeaderTests(TestCase):
    def test_an_id_is_generated_when_none_is_sent(self):
        response = APIClient().get("/health/")
        self.assertTrue(HEX_ID.fullmatch(response[HEADER]))

    def test_every_request_gets_its_own_id(self):
        client = APIClient()
        ids = {client.get("/health/")[HEADER] for _ in range(5)}
        self.assertEqual(len(ids), 5)

    def test_a_well_formed_incoming_id_is_kept(self):
        for value in ("trace-abc.123_X", "a" * 8, "b" * 64):
            with self.subTest(value=value):
                response = APIClient().get("/health/", HTTP_X_REQUEST_ID=value)
                self.assertEqual(response[HEADER], value)

    def test_malformed_incoming_ids_are_replaced(self):
        values = ("short", "x" * 65, "has spaces in it", "<script>alert(1)</script>", "a;b;c;d;e;f")
        for value in values:
            with self.subTest(value=value):
                response = APIClient().get("/health/", HTTP_X_REQUEST_ID=value)
                self.assertNotEqual(response[HEADER], value)
                self.assertTrue(HEX_ID.fullmatch(response[HEADER]))

    def test_error_responses_carry_the_id_too(self):
        client = APIClient()
        cases = [
            (client.get("/api/tickets/"), 401),
            (client.get("/api/does-not-exist/"), 404),
            (client.post("/health/"), 405),
            (client.get("/api/downloads/garbage/"), 403),
        ]
        for response, status_code in cases:
            with self.subTest(status=status_code):
                self.assertEqual(response.status_code, status_code)
                self.assertTrue(HEX_ID.fullmatch(response[HEADER]))

    @override_settings(CORS_ALLOWED_ORIGINS=[ALLOWED_ORIGIN])
    def test_cors_preflight_carries_the_id(self):
        response = APIClient().options(
            "/api/tickets/",
            HTTP_ORIGIN=ALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )
        self.assertTrue(HEX_ID.fullmatch(response[HEADER]))

    @override_settings(CORS_ALLOWED_ORIGINS=[ALLOWED_ORIGIN])
    def test_browsers_are_allowed_to_read_the_id(self):
        response = APIClient().get("/health/", HTTP_ORIGIN=ALLOWED_ORIGIN)
        self.assertIn("X-Request-ID", response["Access-Control-Expose-Headers"])

    def test_the_log_context_is_cleared_after_the_request(self):
        user = UserFactory()
        _client_for(user).get("/api/auth/me/")
        self.assertIsNone(request_id_var.get())
        self.assertIsNone(user_id_var.get())


class AccessLogTests(TestCase):
    def test_one_line_describes_each_request(self):
        with LogCapture() as capture:
            response = APIClient().get("/api/tickets/")
        (line,) = capture.lines
        self.assertEqual(line["logger"], "core.access")
        self.assertEqual(line["message"], "request completed")
        self.assertEqual(line["level"], "INFO")
        self.assertEqual(line["method"], "GET")
        self.assertEqual(line["path"], "/api/tickets/")
        self.assertEqual(line["status"], 401)
        self.assertEqual(line["request_id"], response[HEADER])
        self.assertEqual(line["client_ip"], "127.0.0.1")
        self.assertGreaterEqual(line["duration_ms"], 0)

    def test_the_http_method_is_recorded(self):
        with LogCapture() as capture:
            APIClient().post("/api/token/", {"username": "nobody", "password": "x"})
        self.assertEqual(capture.access()[0]["method"], "POST")

    def test_query_strings_are_never_logged(self):
        with LogCapture() as capture:
            APIClient().get("/api/tickets/?search=hunter2&cursor=abc")
        self.assertEqual(capture.access()[0]["path"], "/api/tickets/")
        self.assertNotIn("hunter2", capture.raw)
        self.assertNotIn("cursor", capture.raw)

    def test_signed_download_tokens_are_redacted(self):
        with LogCapture() as capture:
            APIClient().get("/api/downloads/abc123tokenvalue:xyz/")
        self.assertEqual(capture.access()[0]["path"], "/api/downloads/[redacted]/")
        self.assertNotIn("abc123tokenvalue", capture.raw)

    def test_the_health_check_is_not_logged_at_info(self):
        with LogCapture() as capture:
            response = APIClient().get("/health/")
        self.assertEqual(capture.lines, [])
        self.assertTrue(HEX_ID.fullmatch(response[HEADER]))

    def test_credentials_and_tokens_never_reach_the_logs(self):
        user = UserFactory()
        access = str(RefreshToken.for_user(user).access_token)
        authenticated = APIClient()
        authenticated.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        with LogCapture() as capture:
            authenticated.get("/api/auth/me/")
            login = APIClient().post(
                "/api/token/", {"username": user.username, "password": "pass12345"}
            )
        self.assertEqual(login.status_code, 200)
        self.assertNotIn(access, capture.raw)
        self.assertNotIn(login.data["access"], capture.raw)
        self.assertNotIn(login.data["refresh"], capture.raw)
        self.assertNotIn("pass12345", capture.raw)
        self.assertNotIn(user.username, capture.raw)


class UserIdLoggingTests(TestCase):
    def setUp(self):
        self.user = UserFactory()

    def test_an_authenticated_request_logs_the_user_id(self):
        with LogCapture() as capture:
            _client_for(self.user).get("/api/auth/me/")
        self.assertEqual(capture.access()[0]["user_id"], self.user.id)

    def test_an_anonymous_request_logs_no_user(self):
        with LogCapture() as capture:
            APIClient().get("/api/tickets/")
        self.assertIsNone(capture.access()[0]["user_id"])

    def test_a_rejected_token_logs_no_user(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer garbage")
        with LogCapture() as capture:
            response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)
        self.assertIsNone(capture.access()[0]["user_id"])

    def test_the_user_does_not_leak_into_the_next_request(self):
        with LogCapture() as capture:
            _client_for(self.user).get("/api/auth/me/")
            APIClient().get("/api/tickets/")
        first, second = capture.access()
        self.assertEqual(first["user_id"], self.user.id)
        self.assertIsNone(second["user_id"])

    def test_each_user_is_logged_under_their_own_id(self):
        other = UserFactory()
        with LogCapture() as capture:
            _client_for(self.user).get("/api/auth/me/")
            _client_for(other).get("/api/auth/me/")
        self.assertEqual([line["user_id"] for line in capture.access()], [self.user.id, other.id])


@override_settings(ROOT_URLCONF=TRACE_URLCONF)
class RequestTracingTests(TestCase):
    def setUp(self):
        self.user = UserFactory()

    def test_every_line_of_one_request_shares_its_id(self):
        client = _client_for(self.user)
        with LogCapture() as capture:
            first = client.get("/traced/")
            second = client.get("/traced/")
        self.assertEqual(first.status_code, 200)
        self.assertNotEqual(first[HEADER], second[HEADER])
        self.assertEqual(len(capture.lines), 6)
        for response in (first, second):
            lines = [line for line in capture.lines if line["request_id"] == response[HEADER]]
            messages = [line["message"] for line in lines]
            self.assertEqual(messages, ["loading data", "rendering data", "request completed"])
            self.assertEqual({line["user_id"] for line in lines}, {self.user.id})

    def test_an_incoming_id_is_used_for_the_whole_request(self):
        with LogCapture() as capture:
            response = _client_for(self.user).get("/traced/", HTTP_X_REQUEST_ID="client-supplied-1")
        self.assertEqual(response[HEADER], "client-supplied-1")
        self.assertEqual({line["request_id"] for line in capture.lines}, {"client-supplied-1"})

    def test_an_unhandled_error_is_logged_with_its_traceback_and_the_id(self):
        client = _client_for(self.user, raise_request_exception=False)
        with LogCapture() as capture:
            response = client.get("/broken/")
        self.assertEqual(response.status_code, 500)
        self.assertTrue(HEX_ID.fullmatch(response[HEADER]))
        lines = [line for line in capture.lines if line["request_id"] == response[HEADER]]
        error = next(line for line in lines if line["logger"] == "django.request")
        self.assertEqual(error["level"], "ERROR")
        self.assertIn("RuntimeError: boom", error["exception"])
        access = next(line for line in lines if line["logger"] == "core.access")
        self.assertEqual(access["level"], "ERROR")
        self.assertEqual(access["status"], 500)
        self.assertEqual(access["user_id"], self.user.id)
