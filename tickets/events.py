from realtime.events import publish
from tickets.models import TicketEvent

TICKET_EVENT_TYPE = "ticket.event"
STAFF_ONLY_FIELDS = frozenset({"assignee"})


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
        staff_only=field_changed in STAFF_ONLY_FIELDS,
    )
    return event
