from django.db import transaction
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers, viewsets
from rest_framework.validators import UniqueValidator

from tickets.events import TAG_FIELD, record_event
from tickets.models import Tag, Ticket
from tickets.permissions import IsAdminOrAgentReadOnly
from tickets.schema import tag_schema
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


@tag_schema
class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [IsAdminOrAgentReadOnly]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        actor = self.request.user
        with transaction.atomic():
            for ticket in Ticket.all_objects.filter(tags=instance).iterator():
                record_event(
                    ticket=ticket,
                    actor=actor,
                    field_changed=TAG_FIELD,
                    old_value=instance.name,
                    new_value="",
                )
            instance.delete()
