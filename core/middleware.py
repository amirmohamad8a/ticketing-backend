import logging
import re
import time
import uuid

from django.conf import settings
from django.http import JsonResponse
from django.utils.translation import gettext

from rest_framework.throttling import BaseThrottle

from core.logs import request_id_var, scrub, user_id_var

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_META_KEY = "HTTP_X_REQUEST_ID"
QUIET_PATHS = frozenset({"/health/", "/ready/", "/metrics/"})
REQUEST_TOO_LARGE_CODE = "request_too_large"

_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")

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
        return length > settings.MAX_REQUEST_BODY_BYTES
