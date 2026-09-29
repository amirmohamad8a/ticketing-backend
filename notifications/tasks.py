import logging

from celery import shared_task

from tickets.models import TicketEvent

logger = logging.getLogger(__name__)


@shared_task
def send_ticket_notification(event_id):
    event = TicketEvent.objects.filter(id=event_id).first()
    if event is None:
        return
    logger.info("Sending notification for event %s: %s", event.id, event)
