from django.urls import path

from rest_framework.routers import DefaultRouter

from tickets.views import AttachmentDownloadView, TicketViewSet

router = DefaultRouter()
router.register("tickets", TicketViewSet, basename="ticket")

urlpatterns = [
    *router.urls,
    path(
        "attachments/<int:pk>/download/",
        AttachmentDownloadView.as_view(),
        name="attachment-download",
    ),
]
