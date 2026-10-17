import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tickets.models import Ticket
from tickets.serializers import TicketSerializer

logger = logging.getLogger(__name__)


def change_status(ticket, new_status, request=None):
    context = {"request": request} if request is not None else {}
    serializer = TicketSerializer(
        ticket, data={"status": new_status}, partial=True, context=context
    )
    serializer.is_valid(raise_exception=True)
    return serializer.save()


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


def reopen_on_customer_reply(ticket_id, request=None):
    with transaction.atomic():
        ticket = (
            Ticket.objects.select_for_update()
            .filter(pk=ticket_id, status__in=REOPENABLE_STATUSES)
            .first()
        )
        if ticket is None:
            return False
        change_status(ticket, Ticket.Status.IN_PROGRESS, request)
    return True
