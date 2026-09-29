import logging

from django.db import transaction

from celery import Task, shared_task

from notifications.exceptions import ProviderError
from notifications.models import NotificationLog
from notifications.providers import deliver
from tickets.models import TicketEvent

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 5
RETRY_BACKOFF_MAX_SECONDS = 600


def build_idempotency_key(event_id):
    return f"ticket-event-{event_id}"


class NotificationTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        event_id = args[0] if args else kwargs.get("event_id")
        logger.error(
            "Notification for event %s failed permanently (task %s): %r",
            event_id,
            task_id,
            exc,
        )


@shared_task(
    base=NotificationTask,
    autoretry_for=(ProviderError,),
    retry_backoff=RETRY_BACKOFF_SECONDS,
    retry_backoff_max=RETRY_BACKOFF_MAX_SECONDS,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
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
        deliver(event)
