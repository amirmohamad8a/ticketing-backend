from enum import StrEnum

from core.events import TICKET_EVENT_TYPE, publish
from tickets.models import TicketEvent


class TicketEventField(StrEnum):
    STATUS = "status"
    ASSIGNEE = "assignee"
    PRIORITY = "priority"
    TITLE = "title"
    DESCRIPTION = "description"
    TAG = "tag"
    CONTACT = "contact"
    DELETED = "deleted"
    RESTORED = "restored"
    CHANNEL = "channel"
    CREATED = "created"


TAG_FIELD = TicketEventField.TAG
CONTACT_FIELD = TicketEventField.CONTACT
DELETED_FIELD = TicketEventField.DELETED
RESTORED_FIELD = TicketEventField.RESTORED
STAFF_ONLY_EVENT_FIELDS = frozenset(
    {
        TicketEventField.ASSIGNEE,
        TicketEventField.TAG,
        TicketEventField.CONTACT,
        TicketEventField.DELETED,
        TicketEventField.RESTORED,
    }
)


def tag_changes(old_tags, new_tags):
    old = {tag.pk: tag.name for tag in old_tags}
    new = {tag.pk: tag.name for tag in new_tags}
    removed = sorted(name for pk, name in old.items() if pk not in new)
    added = sorted(name for pk, name in new.items() if pk not in old)
    return [(TAG_FIELD, name, "") for name in removed] + [(TAG_FIELD, "", name) for name in added]


def record_event(ticket, actor, field_changed, old_value, new_value):
    event = TicketEvent.objects.create(
        ticket=ticket,
        actor=actor,
        field_changed=field_changed,
        old_value=old_value,
        new_value=new_value,
    )
    publish(
        TICKET_EVENT_TYPE,
        event.pk,
        event.ticket_id,
        {
            "field_changed": field_changed,
            "old_value": old_value,
            "new_value": new_value,
        },
        staff_only=field_changed in STAFF_ONLY_EVENT_FIELDS,
    )
    return event
