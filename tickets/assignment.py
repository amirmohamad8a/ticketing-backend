from types import SimpleNamespace

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.models import User
from tickets.exceptions import TicketAlreadyAssigned
from tickets.models import Ticket
from tickets.serializers import TicketSerializer


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


def release_tickets(user, actor=None):
    from chat.assignment import route_new_chat

    context = {"request": SimpleNamespace(user=actor)}
    with transaction.atomic():
        tickets = list(
            Ticket.objects.select_for_update().assigned_to(user).unfinished().order_by("pk")
        )
        released = []
        for ticket in tickets:
            serializer = TicketSerializer(
                ticket, data={"assignee": None}, partial=True, context=context
            )
            serializer.is_valid(raise_exception=True)
            released.append(serializer.save())
        for ticket in released:
            if ticket.channel == Ticket.Channel.CHAT:
                route_new_chat(ticket)
    return released
