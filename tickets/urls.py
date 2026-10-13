from django.urls import path

from rest_framework.routers import DefaultRouter

from tickets.canned import CannedReplyViewSet
from tickets.tags import TagViewSet
from tickets.views import AttachmentDownloadView, TicketViewSet

router = DefaultRouter()
router.register("tickets", TicketViewSet, basename="ticket")
router.register("canned-replies", CannedReplyViewSet, basename="canned-reply")
router.register("tags", TagViewSet, basename="tag")

urlpatterns = [
    *router.urls,
    path(
        "attachments/<int:pk>/download/",
        AttachmentDownloadView.as_view(),
        name="attachment-download",
    ),
]
