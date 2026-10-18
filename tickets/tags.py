from tickets.events import TAG_FIELD
from tickets.models import TicketEvent
from tickets.serializers.tags import TagNameField, TagSerializer
from tickets.views.tags import TagViewSet

TAG_EVENT_BATCH_SIZE = 1000


def write_tag_delete_events(tag, ticket_ids, actor):
    for start in range(0, len(ticket_ids), TAG_EVENT_BATCH_SIZE):
        batch = ticket_ids[start : start + TAG_EVENT_BATCH_SIZE]
        TicketEvent.objects.bulk_create(
            [
                TicketEvent(
                    ticket_id=ticket_id,
                    actor=actor,
                    field_changed=TAG_FIELD,
                    old_value=tag.name,
                    new_value="",
                )
                for ticket_id in batch
            ]
        )


__all__ = ["TagNameField", "TagSerializer", "TagViewSet", "write_tag_delete_events"]
