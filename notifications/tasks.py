import logging

from django.db import transaction

from celery import shared_task

from notifications.models import NotificationLog
from tickets.models import TicketEvent

logger = logging.getLogger(__name__)


def build_idempotency_key(event_id):
    return f"ticket-event-{event_id}"


@shared_task
def send_ticket_notification(event_id):
    event = TicketEvent.objects.filter(id=event_id).first()
    if event is None:
        return
    key = build_idempotency_key(event.id)
    with transaction.atomic():
        _, created = NotificationLog.objects.get_or_create(
            idempotency_key=key, defaults={"event": event}
        )
        if not created:
            logger.info("Skipping duplicate notification for %s", key)
            return
        logger.info("Sending notification for event %s: %s", event.id, event)
