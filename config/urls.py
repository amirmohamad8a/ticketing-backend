from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.utils.translation import gettext as _

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts.views import TaggedTokenObtainPairView, TaggedTokenRefreshView
from core.views import SignedDownloadView, health, metrics, ready


def _error_response(status_code, code, message):
    return JsonResponse(
        {"error": {"code": code, "message": message, "details": None}},
        status=status_code,
    )


def handler400(request, exception=None):
    return _error_response(400, "bad_request", _("The request could not be processed."))


def handler404(request, exception):
    return _error_response(404, "not_found", _("Not found."))


def handler500(request):
    return _error_response(500, "server_error", _("An unexpected error occurred."))


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("ready/", ready, name="ready"),
    path("metrics/", metrics, name="metrics"),
    path("api/token/", TaggedTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TaggedTokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/", include("accounts.urls")),
    path("api/downloads/<str:token>/", SignedDownloadView.as_view(), name="signed-download"),
    path("api/", include("accounts.user_urls")),
    path("api/", include("tickets.urls")),
    path("api/", include("stats.urls")),
    path("api/", include("audit.urls")),
    path("api/", include("chat.urls")),
    path("api/", include("chat.widget.urls")),
    path("api/", include("realtime.urls")),
]

if settings.API_DOCS_ENABLED:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
