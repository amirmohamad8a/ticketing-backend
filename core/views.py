import hmac
import os

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from drf_spectacular.utils import extend_schema
from prometheus_client import CONTENT_TYPE_LATEST
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.downloads import read_download_token
from core.health import all_passed, run_checks
from core.metrics import render_metrics


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


@extend_schema(exclude=True)
class SignedDownloadView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "download"

    def get(self, request, token):
        payload = read_download_token(token)
        try:
            handle = default_storage.open(payload["name"], "rb")
        except FileNotFoundError:
            raise Http404
        filename = payload.get("filename") or os.path.basename(payload["name"])
        response = FileResponse(
            handle,
            content_type=payload["content_type"],
            as_attachment=True,
            filename=filename,
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
