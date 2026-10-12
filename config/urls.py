from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts.views import TaggedTokenObtainPairView, TaggedTokenRefreshView
from core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/token/", TaggedTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TaggedTokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("accounts.user_urls")),
    path("api/", include("tickets.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
