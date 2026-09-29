from django.db import transaction

from notifications.tasks import send_ticket_notification
from tickets.models import TicketEvent


def record_event(ticket, actor, field_changed, old_value, new_value):
    event = TicketEvent.objects.create(
        ticket=ticket,
        actor=actor,
        field_changed=field_changed,
        old_value=old_value,
        new_value=new_value,
    )
    transaction.on_commit(lambda: send_ticket_notification.delay(event.id), robust=True)
    return event
