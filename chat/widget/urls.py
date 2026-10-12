from django.urls import path

from chat.widget.views import (
    AttachmentCreateView,
    ConversationCreateView,
    ConversationReadView,
    MessageListCreateView,
    WidgetAttachmentDownloadView,
    WidgetConfigView,
)

urlpatterns = [
    path("widget/config/", WidgetConfigView.as_view(), name="widget-config"),
    path(
        "widget/conversations/",
        ConversationCreateView.as_view(),
        name="widget-conversation-create",
    ),
    path(
        "widget/conversations/<int:pk>/messages/",
        MessageListCreateView.as_view(),
        name="widget-messages",
    ),
    path(
        "widget/conversations/<int:pk>/read/",
        ConversationReadView.as_view(),
        name="widget-conversation-read",
    ),
    path(
        "widget/conversations/<int:pk>/attachments/",
        AttachmentCreateView.as_view(),
        name="widget-conversation-attachments",
    ),
    path(
        "widget/attachments/<int:pk>/download/",
        WidgetAttachmentDownloadView.as_view(),
        name="widget-attachment-download",
    ),
]
