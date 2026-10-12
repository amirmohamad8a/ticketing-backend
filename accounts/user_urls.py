from django.urls import path

from rest_framework.routers import SimpleRouter

from accounts.views import AgentListView, UserViewSet

router = SimpleRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    *router.urls,
    path("agents/", AgentListView.as_view(), name="agent-list"),
]
