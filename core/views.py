import hmac
import logging
import os

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from asgiref.sync import sync_to_async
from drf_spectacular.utils import extend_schema
from prometheus_client import CONTENT_TYPE_LATEST
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.downloads import read_download_token
from core.health import all_passed, run_checks
from core.metrics import render_metrics

DOWNLOAD_CHUNK_SIZE = 64 * 1024
PROXY_WARNING = (
    "X-Forwarded-For is present but NUM_PROXIES is 0, so every client shares one "
    "throttle bucket."
)

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "HEAD"])
@never_cache
def health(request):
    return JsonResponse({"status": "ok"})


@require_http_methods(["GET", "HEAD"])
@never_cache
def ready(request):
    checks = run_checks()
    passed = all_passed(checks)
    body = {"status": "ok" if passed else "unavailable", "checks": checks}
    if settings.NUM_PROXIES == 0 and request.META.get("HTTP_X_FORWARDED_FOR"):
        logger.warning(PROXY_WARNING)
        body["warnings"] = [PROXY_WARNING]
    return JsonResponse(body, status=200 if passed else 503)


def _bearer_token(request):
    scheme, _sep, value = request.META.get("HTTP_AUTHORIZATION", "").partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


@require_http_methods(["GET", "HEAD"])
@never_cache
def metrics(request):
    expected = settings.METRICS_TOKEN
    if not expected:
        raise Http404
    provided = _bearer_token(request)
    if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        response = HttpResponse(status=401)
        response["WWW-Authenticate"] = "Bearer"
        return response
    return HttpResponse(render_metrics(), content_type=CONTENT_TYPE_LATEST)


async def _stream_file(name):
    handle = await sync_to_async(default_storage.open)(name, "rb")
    try:
        while True:
            chunk = await sync_to_async(handle.read)(DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        await sync_to_async(handle.close)()


@extend_schema(exclude=True)
class SignedDownloadView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "download"

    def get(self, request, token):
        payload = read_download_token(token)
        if not default_storage.exists(payload["name"]):
            raise Http404
        filename = payload.get("filename") or os.path.basename(payload["name"])
        response = StreamingHttpResponse(
            _stream_file(payload["name"]),
            content_type=payload["content_type"],
        )
        response["Content-Disposition"] = content_disposition_header(True, filename)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
