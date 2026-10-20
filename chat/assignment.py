from datetime import UTC, datetime

from django.db import transaction

from rest_framework.exceptions import ValidationError

from accounts.models import User
from accounts.permissions import STAFF_ROLES
from chat import presence
from tickets.assignment import assign_ticket
from tickets.models import Ticket

EPOCH = datetime.min.replace(tzinfo=UTC)


def _lock_available_agents(skip_locked=False):
    candidate_ids = presence.available_agent_ids()
    if not candidate_ids:
        return []
    return list(
        User.objects.select_for_update(skip_locked=skip_locked)
        .filter(pk__in=candidate_ids, is_active=True, role__in=STAFF_ROLES)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _routing_key(agent):
    return (agent.open_chats, agent.last_chat_assigned_at or EPOCH, agent.pk)


def _pick_agent(skip_locked=False):
    locked_ids = _lock_available_agents(skip_locked=skip_locked)
    if not locked_ids:
        return None
    eligible = presence.accepting_agents(locked_ids)
    if not eligible:
        return None
    return min(eligible, key=_routing_key)


def route_new_chat(ticket, skip_locked=False):
    with transaction.atomic():
        agent = _pick_agent(skip_locked=skip_locked)
        if agent is None:
            return None
        try:
            assign_ticket(ticket, agent)
        except ValidationError:
            return None
        return agent


def route_queued_chats():
    ticket_ids = list(
        Ticket.objects.chat()
        .unassigned()
        .unfinished()
        .order_by("created_at", "pk")
        .values_list("pk", flat=True)
    )
    assigned = 0
    for ticket_id in ticket_ids:
        with transaction.atomic():
            ticket = (
                Ticket.objects.select_for_update()
                .filter(pk=ticket_id)
                .chat()
                .unassigned()
                .unfinished()
                .first()
            )
            if ticket is None:
                continue
            if route_new_chat(ticket) is None:
                break
            assigned += 1
    return assigned
