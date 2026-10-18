from django.utils.translation import gettext_lazy as _

from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from tickets.models import CannedReply
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
