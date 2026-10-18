import json

from django.utils.translation import gettext

from core.middleware.request_size import REQUEST_TOO_LARGE_CODE, limit_for_path


class BodySizeLimitASGI:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = limit_for_path(scope.get("path", ""))
        if self._declared_too_large(scope, limit):
            await self._send_too_large(send)
            return

        chunks = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body") or b""
            total += len(chunk)
            if total > limit:
                await self._send_too_large(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    def _declared_too_large(scope, limit):
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    return int(value) > limit
                except (TypeError, ValueError):
                    return False
        return False

    @staticmethod
    async def _send_too_large(send):
        payload = json.dumps(
            {
                "error": {
                    "code": REQUEST_TOO_LARGE_CODE,
                    "message": gettext("The request body is too large."),
                    "details": None,
                }
            }
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})
