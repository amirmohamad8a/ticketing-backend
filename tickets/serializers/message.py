from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from tickets.messages import comment_sender_type
from tickets.models import Comment
from tickets.serializers.attachment import AttachmentSerializer
from tickets.validators import MAX_BODY_LENGTH


class CommentSerializer(serializers.ModelSerializer):
    client_msg_id = serializers.CharField(
        max_length=64, required=False, allow_null=True, allow_blank=True
    )
    sender_type = serializers.SerializerMethodField()
    attachments = AttachmentSerializer(many=True, read_only=True)
    system_code = serializers.CharField(
        read_only=True,
        help_text=(
            "Machine-readable reason of a system message, empty for other messages. "
            "Known values: `offline_notice`. Unknown values should be shown with a neutral label."
        ),
    )

    class Meta:
        model = Comment
        fields = [
            "id",
            "ticket",
            "author",
            "visitor",
            "sender_type",
            "kind",
            "system_code",
            "client_msg_id",
            "body",
            "is_internal",
            "attachments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "ticket",
            "author",
            "visitor",
            "kind",
            "system_code",
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
    before = serializers.IntegerField(min_value=0, max_value=2**63 - 1, required=False)

    def validate(self, attrs):
        if "before" in attrs and self.initial_data.get("after") not in (None, ""):
            raise serializers.ValidationError(
                {"before": _("Use either after or before, not both.")}
            )
        return attrs


class MessageListSerializer(serializers.Serializer):
    results = CommentSerializer(many=True, read_only=True)
    has_more = serializers.BooleanField(read_only=True)
    unread_count = serializers.IntegerField(read_only=True)
