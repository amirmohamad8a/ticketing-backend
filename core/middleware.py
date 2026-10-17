import json
import logging
import re
import time
import uuid

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils.translation import gettext

from rest_framework.throttling import BaseThrottle

from core.logs import request_id_var, scrub, user_id_var

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_META_KEY = "HTTP_X_REQUEST_ID"
QUIET_PATHS = frozenset({"/health/", "/ready/", "/metrics/"})
REQUEST_TOO_LARGE_CODE = "request_too_large"
ADMIN_LOGIN_CACHE_PREFIX = "admin_login_attempt"
UPLOAD_PATH_SUFFIXES = ("/attachments/",)
UPLOAD_PATHS = frozenset({"/api/auth/me/"})

_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")


def limit_for_path(path):
    if path in UPLOAD_PATHS or path.endswith(UPLOAD_PATH_SUFFIXES):
        return settings.MAX_UPLOAD_BODY_BYTES
    return settings.MAX_REQUEST_BODY_BYTES


access_logger = logging.getLogger("core.access")


def _resolve_request_id(request):
    candidate = request.META.get(REQUEST_ID_META_KEY, "")
    if _VALID_REQUEST_ID.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = _resolve_request_id(request)
        request.request_id = request_id
        request_token = request_id_var.set(request_id)
        user_token = user_id_var.set(None)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            response[REQUEST_ID_HEADER] = request_id
            self._log_access(request, response, started)
            return response
        finally:
            user_id_var.reset(user_token)
            request_id_var.reset(request_token)

    def _log_access(self, request, response, started):
        if response.status_code >= 500:
            level = logging.ERROR
        elif request.path in QUIET_PATHS:
            level = logging.DEBUG
        else:
            level = logging.INFO
        if not access_logger.isEnabledFor(level):
            return
        access_logger.log(
            level,
            "request completed",
            extra={
                "method": request.method,
                "path": scrub(request.path),
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "client_ip": BaseThrottle().get_ident(request),
            },
        )


class RequestSizeLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._too_large(request):
            return JsonResponse(
                {
                    "error": {
                        "code": REQUEST_TOO_LARGE_CODE,
                        "message": gettext("The request body is too large."),
                        "details": None,
                    }
                },
                status=413,
            )
        return self.get_response(request)

    @staticmethod
    def _too_large(request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return False
        return length > limit_for_path(request.path_info or request.path)


class AdminLoginThrottleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_login_attempt(request) and self._too_many_attempts(request):
            return HttpResponse(
                gettext("Too many login attempts. Please try again later."),
                status=429,
                content_type="text/plain",
            )
        return self.get_response(request)

    @staticmethod
    def _is_login_attempt(request):
        return request.method == "POST" and request.path_info == settings.ADMIN_LOGIN_PATH

    @staticmethod
    def _too_many_attempts(request):
        max_attempts = settings.ADMIN_LOGIN_MAX_ATTEMPTS
        if max_attempts <= 0:
            return False
        ident = BaseThrottle().get_ident(request) or "unknown"
        key = f"{ADMIN_LOGIN_CACHE_PREFIX}:{ident}"
        window = settings.ADMIN_LOGIN_WINDOW_SECONDS
        try:
            if cache.add(key, 1, window):
                return False
            attempts = cache.incr(key)
        except ValueError:
            cache.set(key, 1, window)
            return False
        return attempts > max_attempts


class BodySizeLimitASGI:
    """Reject oversized request bodies before Django spools them to disk.

    Django's ASGI handler reads the whole body into a spooled temp file before
    the middleware stack runs, so a Content-Length check in middleware is too
    late for a chunked or lying client. This thin wrapper counts the bytes on
    ``http.request`` events and answers 413 as soon as the limit is crossed. A
    body within the limit is buffered in memory and replayed to the inner app.
    """

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
