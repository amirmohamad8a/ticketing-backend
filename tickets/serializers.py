from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from chat.models import Site, Visitor
from core.uploads import clean_file_name, ensure_content_matches
from tickets.messages import comment_sender_type
from tickets.models import Attachment, Comment, Ticket, TicketEvent, TicketRating
from tickets.rules import validate_assignee, validate_status_transition, validate_tags
from tickets.services import create_ticket, update_ticket
from tickets.validators import MAX_BODY_LENGTH

STAFF_ONLY_RESPONSE_FIELDS = frozenset({"tags", "first_response_due_at", "visitor", "site"})


class TicketVisitorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Visitor
        fields = ["id", "name", "phone", "email"]
        read_only_fields = fields


class TicketSiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ["id", "name"]
        read_only_fields = fields


class TicketSerializer(serializers.ModelSerializer):
    visitor = TicketVisitorSerializer(read_only=True, allow_null=True)
    site = TicketSiteSerializer(read_only=True, allow_null=True)
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "title",
            "description",
            "status",
            "priority",
            "channel",
            "customer",
            "visitor",
            "site",
            "assignee",
            "tags",
            "first_response_due_at",
            "unread_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "channel",
            "customer",
            "first_response_due_at",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"description": {"max_length": MAX_BODY_LENGTH}}

    def get_unread_count(self, obj) -> int:
        return getattr(obj, "unread_count", 0)

    def validate_status(self, value):
        if self.instance is None:
            return value
        return validate_status_transition(self.instance, value)

    def validate_assignee(self, value):
        current = self.instance.assignee if self.instance is not None else None
        return validate_assignee(value, current)

    def validate_tags(self, value):
        return validate_tags(value)

    def _get_actor(self):
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if actor is not None and not actor.is_authenticated:
            return None
        return actor

    def create(self, validated_data):
        return create_ticket(self._get_actor(), validated_data)

    def update(self, instance, validated_data):
        return update_ticket(instance, self._get_actor(), validated_data)


class CustomerTicketSerializer(TicketSerializer):
    class Meta(TicketSerializer.Meta):
        fields = [
            field
            for field in TicketSerializer.Meta.fields
            if field not in STAFF_ONLY_RESPONSE_FIELDS
        ]
        read_only_fields = [
            *TicketSerializer.Meta.read_only_fields,
            "status",
            "priority",
            "assignee",
        ]


class TicketEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketEvent
        fields = [
            "id",
            "ticket",
            "actor",
            "field_changed",
            "old_value",
            "new_value",
            "created_at",
        ]
        read_only_fields = fields


class CommentSerializer(serializers.ModelSerializer):
    client_msg_id = serializers.CharField(
        max_length=64, required=False, allow_null=True, allow_blank=True
    )
    sender_type = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            "id",
            "ticket",
            "author",
            "visitor",
            "sender_type",
            "kind",
            "client_msg_id",
            "body",
            "is_internal",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "ticket",
            "author",
            "visitor",
            "kind",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"body": {"max_length": MAX_BODY_LENGTH}}

    def get_sender_type(self, obj) -> str:
        return comment_sender_type(obj)

    def validate_client_msg_id(self, value):
        return value or None


class MessageQuerySerializer(serializers.Serializer):
    after = serializers.IntegerField(min_value=0, max_value=2**63 - 1, default=0)


class MessageListSerializer(serializers.Serializer):
    results = CommentSerializer(many=True, read_only=True)
    has_more = serializers.BooleanField(read_only=True)
    unread_count = serializers.IntegerField(read_only=True)


class ReadMarkSerializer(serializers.Serializer):
    last_read_comment_id = serializers.IntegerField(
        required=False, min_value=1, max_value=2**63 - 1
    )


class ReadStateSerializer(serializers.Serializer):
    last_read_comment_id = serializers.IntegerField(read_only=True)
    unread_count = serializers.IntegerField(read_only=True)


class TicketRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketRating
        fields = ["score", "comment", "created_at"]
        read_only_fields = ["created_at"]


class AttachmentSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            "id",
            "ticket",
            "comment",
            "file",
            "original_name",
            "download_url",
            "uploaded_by",
            "size",
            "content_type",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "ticket",
            "comment",
            "original_name",
            "uploaded_by",
            "size",
            "content_type",
            "created_at",
        ]
        extra_kwargs = {"file": {"write_only": True}}

    def get_download_url(self, obj) -> str:
        path = reverse("attachment-download", args=[obj.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path

    def validate_file(self, value):
        if value.size > Attachment.MAX_SIZE_BYTES:
            max_mb = Attachment.MAX_SIZE_BYTES // (1024 * 1024)
            message = _("File too large. Max size is %(max_mb)sMB.")
            raise serializers.ValidationError(message % {"max_mb": max_mb})
        content_type = getattr(value, "content_type", "") or ""
        if content_type not in Attachment.ALLOWED_CONTENT_TYPES:
            message = _("File type '%(content_type)s' is not allowed.")
            raise serializers.ValidationError(message % {"content_type": content_type})
        ensure_content_matches(value, content_type)
        return value

    def create(self, validated_data):
        file_obj = validated_data["file"]
        validated_data["size"] = file_obj.size
        validated_data["content_type"] = getattr(file_obj, "content_type", "") or ""
        validated_data["original_name"] = clean_file_name(file_obj.name)
        return super().create(validated_data)
