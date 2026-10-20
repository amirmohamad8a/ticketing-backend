from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from audit.cursors import KINDS, MAX_ID, InvalidCursor, decode_cursor


class AuditQuerySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=KINDS, required=False)
    actor = serializers.IntegerField(required=False, min_value=1, max_value=MAX_ID)
    field_changed = serializers.CharField(required=False, max_length=50)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    cursor = serializers.CharField(required=False, max_length=200)

    def validate_cursor(self, value):
        try:
            return decode_cursor(value)
        except InvalidCursor as exc:
            raise serializers.ValidationError(_("The cursor is invalid.")) from exc

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise serializers.ValidationError(
                {"date_from": _("The start date must not be after the end date.")}
            )
        return attrs


class AuditEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    kind = serializers.ChoiceField(choices=KINDS, read_only=True)
    ticket = serializers.IntegerField(read_only=True, allow_null=True)
    user = serializers.IntegerField(read_only=True, allow_null=True)
    actor = serializers.IntegerField(read_only=True, allow_null=True)
    actor_username = serializers.CharField(read_only=True, allow_null=True)
    field_changed = serializers.CharField(read_only=True)
    old_value = serializers.CharField(read_only=True)
    new_value = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class AuditPageSerializer(serializers.Serializer):
    next = serializers.URLField(read_only=True, allow_null=True)
    results = AuditEntrySerializer(many=True, read_only=True)
