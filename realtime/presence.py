from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q

from accounts.models import User
from accounts.permissions import STAFF_ROLES
from chat.conversations import FINISHED_STATUSES
from tickets.models import Ticket

CACHE_PREFIX = "presence:"
STATUS_AVAILABLE = "available"
STATUS_AWAY = "away"
STATUSES = (STATUS_AVAILABLE, STATUS_AWAY)
ACTIVE_STATUSES = [value for value in Ticket.Status.values if value not in FINISHED_STATUSES]


def _key(user_id):
    return f"{CACHE_PREFIX}{user_id}"


def heartbeat(user_id, default_status=STATUS_AVAILABLE):
    key = _key(user_id)
    ttl = settings.PRESENCE_TTL_SECONDS
    state = cache.get(key)
    if state is None:
        cache.add(key, {"status": default_status}, timeout=ttl)
        state = cache.get(key) or {"status": default_status}
    else:
        cache.touch(key, ttl)
    return state["status"]


def set_status(user_id, status):
    if status not in STATUSES:
        raise ValueError(f"Unknown presence status: {status!r}")
    cache.set(_key(user_id), {"status": status}, timeout=settings.PRESENCE_TTL_SECONDS)


def get_statuses(user_ids):
    keys = {_key(user_id): user_id for user_id in user_ids}
    if not keys:
        return {}
    found = cache.get_many(list(keys))
    return {keys[key]: state["status"] for key, state in found.items()}


def online_agents():
    agents = list(
        User.objects.filter(is_active=True, role__in=STAFF_ROLES)
        .annotate(
            open_chats=Count(
                "assigned_tickets",
                filter=Q(
                    assigned_tickets__channel=Ticket.Channel.CHAT,
                    assigned_tickets__is_deleted=False,
                    assigned_tickets__status__in=ACTIVE_STATUSES,
                ),
            )
        )
        .order_by("first_name", "last_name", "username", "id")
    )
    statuses = get_statuses([agent.pk for agent in agents])
    rows = []
    for agent in agents:
        status = statuses.get(agent.pk)
        if status is None:
            continue
        rows.append(
            {
                "id": agent.pk,
                "name": agent.get_full_name() or agent.username,
                "role": agent.role,
                "status": status,
                "max_concurrent_chats": agent.max_concurrent_chats,
                "open_chats": agent.open_chats,
                "accepting_chats": (
                    status == STATUS_AVAILABLE and agent.open_chats < agent.max_concurrent_chats
                ),
            }
        )
    return rows
