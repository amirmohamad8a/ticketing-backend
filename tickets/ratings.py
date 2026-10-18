from django.db import IntegrityError, transaction

from tickets.exceptions import TicketAlreadyRated, TicketNotResolved
from tickets.models import Ticket, TicketRating


def rate_ticket(ticket, score, comment=""):
    if ticket.status not in Ticket.FINISHED_STATUSES:
        raise TicketNotResolved
    if TicketRating.objects.filter(ticket=ticket).exists():
        raise TicketAlreadyRated
    try:
        with transaction.atomic():
            return TicketRating.objects.create(ticket=ticket, score=score, comment=comment)
    except IntegrityError:
        raise TicketAlreadyRated from None
