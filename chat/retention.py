import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from chat.models import Visitor
from tickets.models import Ticket

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def retention_cutoff(days=None, now=None):
    now = now or timezone.now()
    days = settings.VISITOR_RETENTION_DAYS if days is None else days
    return now - timedelta(days=days)


def redactable_visitors(cutoff):
    has_unfinished_ticket = Exists(
        Ticket.objects.filter(visitor=OuterRef("pk")).exclude(status__in=Ticket.FINISHED_STATUSES)
    )
    return (
        Visitor.objects.filter(last_seen_at__lt=cutoff)
        .annotate(has_unfinished_ticket=has_unfinished_ticket)
        .filter(has_unfinished_ticket=False)
        .exclude(Q(name="", phone="", email=""))
    )


def count_redactable_visitors(days=None, now=None):
    return redactable_visitors(retention_cutoff(days, now)).count()


def _redact_batch(cutoff, batch_size):
    with transaction.atomic():
        ids = list(
            redactable_visitors(cutoff)
            .select_for_update(skip_locked=True, of=("self",))
            .order_by("pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        if not ids:
            return 0
        Visitor.objects.filter(pk__in=ids).update(name="", phone="", email="")
    return len(ids)


def redact_stale_visitors(days=None, now=None, batch_size=BATCH_SIZE):
    cutoff = retention_cutoff(days, now)
    redacted = 0
    while True:
        removed = _redact_batch(cutoff, batch_size)
        redacted += removed
        if removed < batch_size:
            break
    logger.info(
        "Visitor retention finished",
        extra={"redacted": redacted, "cutoff": cutoff.isoformat()},
    )
    return redacted


def deletable_visitors(cutoff):
    has_ticket = Exists(Ticket.all_objects.filter(visitor=OuterRef("pk")))
    return (
        Visitor.objects.filter(last_seen_at__lt=cutoff)
        .annotate(has_ticket=has_ticket)
        .filter(has_ticket=False)
    )


def count_deletable_visitors(days=None, now=None):
    return deletable_visitors(retention_cutoff(days, now)).count()


def _delete_batch(cutoff, batch_size):
    with transaction.atomic():
        ids = list(
            deletable_visitors(cutoff)
            .select_for_update(skip_locked=True, of=("self",))
            .order_by("pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        if not ids:
            return 0
        Visitor.objects.filter(pk__in=ids).delete()
    return len(ids)


def delete_stale_visitors(days=None, now=None, batch_size=BATCH_SIZE):
    cutoff = retention_cutoff(days, now)
    deleted = 0
    while True:
        removed = _delete_batch(cutoff, batch_size)
        deleted += removed
        if removed < batch_size:
            break
    logger.info(
        "Orphan visitor purge finished",
        extra={"deleted": deleted, "cutoff": cutoff.isoformat()},
    )
    return deleted


def purge_stale_visitors(days=None, now=None, batch_size=BATCH_SIZE):
    deleted = delete_stale_visitors(days, now, batch_size)
    redacted = redact_stale_visitors(days, now, batch_size)
    return {"deleted": deleted, "redacted": redacted}
