from django.utils.translation import gettext_lazy as _

from rest_framework import serializers, viewsets
from rest_framework.validators import UniqueValidator

from accounts.permissions import IsAgentOrAdmin
from tickets.models import CannedReply
from tickets.schema import canned_reply_schema
from tickets.validators import MAX_SHORTCUT_LENGTH, normalize_shortcut, validate_shortcut


class ShortcutField(serializers.CharField):
    def to_internal_value(self, data):
        return normalize_shortcut(super().to_internal_value(data))


class CannedReplySerializer(serializers.ModelSerializer):
    shortcut = ShortcutField(
        max_length=MAX_SHORTCUT_LENGTH,
        validators=[
            validate_shortcut,
            UniqueValidator(
                queryset=CannedReply.objects.all(),
                message=_("A canned reply with that shortcut already exists."),
            ),
        ],
    )

    class Meta:
        model = CannedReply
        fields = ["id", "title", "shortcut", "body", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


@canned_reply_schema
class CannedReplyViewSet(viewsets.ModelViewSet):
    queryset = CannedReply.objects.all()
    serializer_class = CannedReplySerializer
    permission_classes = [IsAgentOrAdmin]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
