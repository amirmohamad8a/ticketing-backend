from django.urls import path

from chat.widget.views import (
    AttachmentCreateView,
    ConversationContactView,
    ConversationCreateView,
    ConversationRatingView,
    ConversationReadView,
    MessageListCreateView,
    WidgetAttachmentDownloadView,
    WidgetChallengeView,
    WidgetConfigView,
    WidgetSocketTicketView,
)

urlpatterns = [
    path("widget/config/", WidgetConfigView.as_view(), name="widget-config"),
    path("widget/challenge/", WidgetChallengeView.as_view(), name="widget-challenge"),
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
        "widget/conversations/<int:pk>/contact/",
        ConversationContactView.as_view(),
        name="widget-conversation-contact",
    ),
    path(
        "widget/conversations/<int:pk>/rating/",
        ConversationRatingView.as_view(),
        name="widget-conversation-rating",
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
    path("widget/ws/ticket/", WidgetSocketTicketView.as_view(), name="widget-ws-ticket"),
]
