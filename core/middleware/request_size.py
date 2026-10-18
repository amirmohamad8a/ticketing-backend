from django.conf import settings
from django.http import JsonResponse
from django.utils.translation import gettext

REQUEST_TOO_LARGE_CODE = "request_too_large"
UPLOAD_PATH_SUFFIXES = ("/attachments/",)
UPLOAD_PATHS = frozenset({"/api/auth/me/"})


def limit_for_path(path):
    if path in UPLOAD_PATHS or path.endswith(UPLOAD_PATH_SUFFIXES):
        return settings.MAX_UPLOAD_BODY_BYTES
    return settings.MAX_REQUEST_BODY_BYTES


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
