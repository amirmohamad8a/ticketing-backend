from django.db import transaction
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers, viewsets
from rest_framework.validators import UniqueValidator

from tickets.events import TAG_FIELD
from tickets.models import Tag, Ticket, TicketEvent
from tickets.permissions import IsAdminOrAgentReadOnly
from tickets.schema import tag_schema
from tickets.validators import MAX_TAG_NAME_LENGTH, normalize_tag_name

TAG_EVENT_BATCH_SIZE = 1000


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
            ticket_ids = list(
                Ticket.all_objects.filter(tags=instance).order_by("pk").values_list("pk", flat=True)
            )
            for start in range(0, len(ticket_ids), TAG_EVENT_BATCH_SIZE):
                batch = ticket_ids[start : start + TAG_EVENT_BATCH_SIZE]
                TicketEvent.objects.bulk_create(
                    [
                        TicketEvent(
                            ticket_id=ticket_id,
                            actor=actor,
                            field_changed=TAG_FIELD,
                            old_value=instance.name,
                            new_value="",
                        )
                        for ticket_id in batch
                    ]
                )
            instance.delete()
