from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from rest_framework import status
from rest_framework.exceptions import APIException

from accounts.models import User
from tickets.models import Ticket
from tickets.serializers import TicketSerializer


class TicketAlreadyAssigned(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _("This ticket is already assigned to someone else.")
    default_code = "ticket_already_assigned"


def assign_ticket(ticket, assignee, request=None):
    context = {"request": request} if request is not None else {}
    serializer = TicketSerializer(
        ticket, data={"assignee": assignee.pk}, partial=True, context=context
    )
    serializer.is_valid(raise_exception=True)
    ticket = serializer.save()
    if ticket.channel == Ticket.Channel.CHAT:
        User.objects.filter(pk=assignee.pk).update(last_chat_assigned_at=timezone.now())
    return ticket


def claim_ticket(ticket_id, claimer, request=None):
    with transaction.atomic():
        ticket = get_object_or_404(Ticket.objects.select_for_update(), pk=ticket_id)
        if ticket.assignee_id == claimer.pk:
            return ticket
        if ticket.assignee_id is not None:
            raise TicketAlreadyAssigned
        return assign_ticket(ticket, claimer, request)
