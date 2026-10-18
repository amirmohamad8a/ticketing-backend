import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tickets.models import Ticket
from tickets.services import update_ticket

logger = logging.getLogger(__name__)


def _actor(actor):
    if actor is not None and hasattr(actor, "user"):
        return actor.user
    return actor


def change_status(ticket, new_status, actor=None):
    return update_ticket(ticket, _actor(actor), {"status": new_status})


def _close_if_due(ticket_id, cutoff):
    with transaction.atomic():
        ticket = (
            Ticket.objects.select_for_update()
            .filter(pk=ticket_id, status=Ticket.Status.RESOLVED, resolved_at__lte=cutoff)
            .first()
        )
        if ticket is None:
            return False
        change_status(ticket, Ticket.Status.CLOSED)
    return True


def close_due_tickets(now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(days=settings.AUTO_CLOSE_AFTER_DAYS)
    ticket_ids = list(
        Ticket.objects.filter(status=Ticket.Status.RESOLVED, resolved_at__lte=cutoff)
        .order_by("resolved_at", "pk")
        .values_list("pk", flat=True)
    )
    closed = 0
    for ticket_id in ticket_ids:
        try:
            if _close_if_due(ticket_id, cutoff):
                closed += 1
        except Exception:
            logger.exception("Failed to auto-close a ticket", extra={"ticket_id": ticket_id})
    logger.info("Auto-close finished", extra={"closed": closed, "candidates": len(ticket_ids)})
    return closed


REOPENABLE_STATUSES = (*Ticket.FINISHED_STATUSES, Ticket.Status.WAITING_ON_CUSTOMER)


def reopen_on_customer_reply(ticket_id, actor=None):
    with transaction.atomic():
        ticket = (
            Ticket.objects.select_for_update()
            .filter(pk=ticket_id, status__in=REOPENABLE_STATUSES)
            .first()
        )
        if ticket is None:
            return False
        change_status(ticket, Ticket.Status.IN_PROGRESS, _actor(actor))
    return True
