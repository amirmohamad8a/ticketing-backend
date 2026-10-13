from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

from rest_framework import status
from rest_framework.exceptions import APIException

from tickets.models import Ticket, TicketRating


class TicketNotResolved(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _("A ticket can only be rated after it has been resolved.")
    default_code = "ticket_not_resolved"


class TicketAlreadyRated(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _("This ticket has already been rated.")
    default_code = "ticket_already_rated"


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
