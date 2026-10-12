from django.urls import path

from rest_framework.routers import SimpleRouter

from accounts.views import AgentListView, AvatarDownloadView, UserViewSet

router = SimpleRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    *router.urls,
    path("agents/", AgentListView.as_view(), name="agent-list"),
    path("avatars/<int:pk>/download/", AvatarDownloadView.as_view(), name="avatar-download"),
]
