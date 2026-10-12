from django.urls import reverse

from rest_framework import serializers

from accounts.serializers import PhoneField
from accounts.validators import validate_iranian_mobile
from chat.availability import agents_available
from chat.models import Site
from tickets.models import Comment, Ticket
from tickets.serializers import AttachmentSerializer, CommentSerializer

MAX_MESSAGE_LENGTH = 4000


def client_msg_id_field():
    return serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=64)


class WidgetConfigSerializer(serializers.ModelSerializer):
    agents_available = serializers.SerializerMethodField()

    class Meta:
        model = Site
        fields = [
            "name",
            "greeting",
            "primary_color",
            "position",
            "offline_timeout_minutes",
            "require_name",
            "require_contact",
            "agents_available",
        ]
        read_only_fields = fields

    def get_agents_available(self, obj) -> bool:
        return agents_available(obj)


class WidgetAttachmentSerializer(AttachmentSerializer):
    class Meta(AttachmentSerializer.Meta):
        fields = [
            "id",
            "file",
            "original_name",
            "download_url",
            "size",
            "content_type",
            "created_at",
        ]
        read_only_fields = ["id", "original_name", "size", "content_type", "created_at"]

    def get_download_url(self, obj) -> str:
        path = reverse("widget-attachment-download", args=[obj.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path


class WidgetMessageSerializer(CommentSerializer):
    sender_name = serializers.SerializerMethodField()
    attachments = WidgetAttachmentSerializer(many=True, read_only=True)

    class Meta(CommentSerializer.Meta):
        fields = [
            "id",
            "sender_type",
            "sender_name",
            "kind",
            "client_msg_id",
            "body",
            "attachments",
            "created_at",
        ]
        read_only_fields = fields

    def get_sender_name(self, obj) -> str:
        if obj.kind == Comment.Kind.SYSTEM:
            return ""
        if obj.visitor_id:
            return obj.visitor.name
        if obj.author_id:
            return obj.author.get_full_name()
        return ""


class WidgetConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ["id", "status", "channel", "created_at"]
        read_only_fields = fields


class WidgetConversationStartSerializer(serializers.Serializer):
    token = serializers.CharField(read_only=True)
    conversation = WidgetConversationSerializer(read_only=True)
    message = WidgetMessageSerializer(read_only=True)
    agents_available = serializers.BooleanField(read_only=True)


class WidgetMessageListSerializer(serializers.Serializer):
    results = WidgetMessageSerializer(many=True, read_only=True)
    has_more = serializers.BooleanField(read_only=True)
    agents_available = serializers.BooleanField(read_only=True)


class ConversationCreateSerializer(serializers.Serializer):
    site_key = serializers.CharField(required=False, max_length=64)
    body = serializers.CharField(max_length=MAX_MESSAGE_LENGTH)
    client_msg_id = client_msg_id_field()
    name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    phone = PhoneField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=32,
        validators=[validate_iranian_mobile],
    )
    email = serializers.EmailField(required=False, allow_blank=True, max_length=254)


class WidgetMessageInputSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=MAX_MESSAGE_LENGTH)
    client_msg_id = client_msg_id_field()


class WidgetMessageQuerySerializer(serializers.Serializer):
    after = serializers.IntegerField(min_value=0, max_value=2**63 - 1, default=0)


class WidgetUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    body = serializers.CharField(allow_blank=True, max_length=MAX_MESSAGE_LENGTH, default="")
    client_msg_id = client_msg_id_field()
