from django.db import transaction
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from accounts.models import User
from core.uploads import clean_file_name, ensure_content_matches
from tickets.events import record_event
from tickets.messages import comment_sender_type
from tickets.models import Attachment, Comment, Ticket, TicketEvent


class TicketSerializer(serializers.ModelSerializer):
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "title",
            "description",
            "status",
            "priority",
            "customer",
            "assignee",
            "unread_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "customer", "created_at", "updated_at"]

    def get_unread_count(self, obj) -> int:
        return getattr(obj, "unread_count", 0)

    def validate_status(self, value):
        if self.instance is None:
            return value
        current_status = self.instance.status
        if value == current_status:
            return value
        allowed = Ticket.STATUS_TRANSITIONS.get(current_status, set())
        if value not in allowed:
            message = _("Cannot transition status from '%(current)s' to '%(new)s'.")
            raise serializers.ValidationError(message % {"current": current_status, "new": value})
        return value

    def validate_assignee(self, value):
        if value is None:
            return value
        if self.instance is not None and value == self.instance.assignee:
            return value
        if value.role == User.Role.CUSTOMER:
            raise serializers.ValidationError(
                _("Tickets can only be assigned to an agent or admin.")
            )
        if not value.is_active:
            raise serializers.ValidationError(_("Tickets cannot be assigned to an inactive user."))
        return value

    def _get_actor(self):
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if actor is not None and not actor.is_authenticated:
            return None
        return actor

    def create(self, validated_data):
        actor = self._get_actor()

        with transaction.atomic():
            ticket = super().create(validated_data)
            record_event(
                ticket=ticket,
                actor=actor,
                field_changed="created",
                old_value="",
                new_value=ticket.status,
            )

        return ticket

    def update(self, instance, validated_data):
        actor = self._get_actor()

        changes = []
        if "status" in validated_data and validated_data["status"] != instance.status:
            changes.append(("status", instance.status, validated_data["status"]))
        if "assignee" in validated_data and validated_data["assignee"] != instance.assignee:
            old_assignee = instance.assignee.username if instance.assignee else ""
            new_assignee = validated_data["assignee"].username if validated_data["assignee"] else ""
            changes.append(("assignee", old_assignee, new_assignee))

        with transaction.atomic():
            instance = super().update(instance, validated_data)
            for field_changed, old_value, new_value in changes:
                record_event(
                    ticket=instance,
                    actor=actor,
                    field_changed=field_changed,
                    old_value=old_value,
                    new_value=new_value,
                )

        return instance


class CustomerTicketSerializer(TicketSerializer):
    class Meta(TicketSerializer.Meta):
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

    def get_sender_type(self, obj) -> str:
        return comment_sender_type(obj)

    def validate_client_msg_id(self, value):
        return value or None


class ReadMarkSerializer(serializers.Serializer):
    last_read_comment_id = serializers.IntegerField(
        required=False, min_value=1, max_value=2**63 - 1
    )


class ReadStateSerializer(serializers.Serializer):
    last_read_comment_id = serializers.IntegerField(read_only=True)
    unread_count = serializers.IntegerField(read_only=True)


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
