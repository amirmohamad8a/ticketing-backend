from datetime import datetime, timezone

from django.db import transaction
from django.db.models import Count

from rest_framework.exceptions import ValidationError

from accounts.models import User
from accounts.permissions import STAFF_ROLES
from realtime import presence
from tickets.assignment import assign_ticket

EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _lock_available_agents():
    candidate_ids = presence.available_agent_ids()
    if not candidate_ids:
        return []
    return list(
        User.objects.select_for_update()
        .filter(pk__in=candidate_ids, is_active=True, role__in=STAFF_ROLES)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _routing_key(agent):
    return (agent.open_chats, agent.last_chat_assigned_at or EPOCH, agent.pk)


def _pick_agent():
    locked_ids = _lock_available_agents()
    if not locked_ids:
        return None
    agents = User.objects.filter(pk__in=locked_ids).annotate(
        open_chats=Count("assigned_tickets", filter=presence.OPEN_CHAT_FILTER)
    )
    eligible = [agent for agent in agents if agent.open_chats < agent.max_concurrent_chats]
    if not eligible:
        return None
    return min(eligible, key=_routing_key)


def route_new_chat(ticket):
    with transaction.atomic():
        agent = _pick_agent()
        if agent is None:
            return None
        try:
            assign_ticket(ticket, agent)
        except ValidationError:
            return None
        return agent
