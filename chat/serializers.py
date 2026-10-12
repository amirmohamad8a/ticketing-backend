from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers

from chat.models import Site
from chat.validators import MAX_ORIGINS, normalize_origin


class OriginField(serializers.CharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            return normalize_origin(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)


class SiteSerializer(serializers.ModelSerializer):
    allowed_origins = serializers.ListField(
        child=OriginField(max_length=255),
        required=False,
        allow_empty=True,
        max_length=MAX_ORIGINS,
    )

    class Meta:
        model = Site
        fields = [
            "id",
            "name",
            "key",
            "allowed_origins",
            "is_active",
            "greeting",
            "primary_color",
            "position",
            "offline_timeout_minutes",
            "require_name",
            "require_contact",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "key", "created_at", "updated_at"]

    def validate_allowed_origins(self, value):
        return list(dict.fromkeys(value))
