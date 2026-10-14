import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from chat.models import Visitor
from tickets.models import Comment, Ticket

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def retention_cutoff(days=None, now=None):
    now = now or timezone.now()
    days = settings.VISITOR_RETENTION_DAYS if days is None else days
    return now - timedelta(days=days)


def stale_visitors(cutoff):
    return Visitor.objects.filter(last_seen_at__lt=cutoff).filter(
        ~Exists(Ticket.all_objects.filter(visitor=OuterRef("pk"))),
        ~Exists(Comment.objects.filter(visitor=OuterRef("pk"))),
    )


def count_stale_visitors(days=None, now=None):
    return stale_visitors(retention_cutoff(days, now)).count()


def _delete_batch(cutoff, batch_size):
    with transaction.atomic():
        ids = list(
            stale_visitors(cutoff)
            .select_for_update(skip_locked=True, of=("self",))
            .order_by("pk")
            .values_list("pk", flat=True)[:batch_size]
        )
        if not ids:
            return 0
        Visitor.objects.filter(pk__in=ids).delete()
    return len(ids)


def purge_stale_visitors(days=None, now=None, batch_size=BATCH_SIZE):
    cutoff = retention_cutoff(days, now)
    deleted = 0
    while True:
        removed = _delete_batch(cutoff, batch_size)
        deleted += removed
        if removed < batch_size:
            break
    logger.info(
        "Visitor retention finished",
        extra={"deleted": deleted, "cutoff": cutoff.isoformat()},
    )
    return deleted
