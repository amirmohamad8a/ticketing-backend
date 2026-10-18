from django.utils.translation import gettext_lazy as _

from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from tickets.models import Tag
from tickets.validators import MAX_TAG_NAME_LENGTH, normalize_tag_name


class TagNameField(serializers.CharField):
    def to_internal_value(self, data):
        return normalize_tag_name(super().to_internal_value(data))


class TagSerializer(serializers.ModelSerializer):
    name = TagNameField(
        max_length=MAX_TAG_NAME_LENGTH,
        validators=[
            UniqueValidator(
                queryset=Tag.objects.all(),
                lookup="iexact",
                message=_("A tag with that name already exists."),
            ),
        ],
    )

    class Meta:
        model = Tag
        fields = ["id", "name", "color", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]
