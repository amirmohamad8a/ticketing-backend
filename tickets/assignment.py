from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.models import User
from tickets.exceptions import TicketAlreadyAssigned
from tickets.models import Ticket
from tickets.services import update_ticket


def _actor(actor):
    if actor is not None and hasattr(actor, "user"):
        return actor.user
    return actor


def assign_ticket(ticket, assignee, actor=None):
    ticket = update_ticket(ticket, _actor(actor), {"assignee": assignee})
    if ticket.channel == Ticket.Channel.CHAT:
        User.objects.filter(pk=assignee.pk).update(last_chat_assigned_at=timezone.now())
    return ticket


def claim_ticket(ticket_id, claimer, actor=None):
    with transaction.atomic():
        ticket = get_object_or_404(Ticket.objects.select_for_update(), pk=ticket_id)
        if ticket.assignee_id == claimer.pk:
            return ticket
        if ticket.assignee_id is not None:
            raise TicketAlreadyAssigned
        return assign_ticket(ticket, claimer, actor)


def release_tickets(user, actor=None):
    from chat.assignment import route_new_chat

    with transaction.atomic():
        tickets = list(
            Ticket.objects.select_for_update().assigned_to(user).unfinished().order_by("pk")
        )
        released = [update_ticket(ticket, _actor(actor), {"assignee": None}) for ticket in tickets]
        for ticket in released:
            if ticket.channel == Ticket.Channel.CHAT:
                route_new_chat(ticket)
    return released
