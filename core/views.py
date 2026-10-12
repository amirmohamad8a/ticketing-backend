import os

from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from core.downloads import read_download_token


@require_http_methods(["GET", "HEAD"])
@never_cache
def health(request):
    return JsonResponse({"status": "ok"})


@extend_schema(exclude=True)
class SignedDownloadView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

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
