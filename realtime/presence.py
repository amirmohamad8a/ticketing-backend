from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q

from accounts.models import User
from accounts.permissions import STAFF_ROLES
from tickets.models import Ticket

CACHE_PREFIX = "presence:"
STATUS_AVAILABLE = "available"
STATUS_AWAY = "away"
STATUSES = (STATUS_AVAILABLE, STATUS_AWAY)
ACTIVE_STATUSES = [value for value in Ticket.Status.values if value not in Ticket.FINISHED_STATUSES]
OPEN_CHAT_FILTER = Q(
    assigned_tickets__channel=Ticket.Channel.CHAT,
    assigned_tickets__is_deleted=False,
    assigned_tickets__status__in=ACTIVE_STATUSES,
)


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


def available_agent_ids():
    staff_ids = list(
        User.objects.filter(is_active=True, role__in=STAFF_ROLES).values_list("pk", flat=True)
    )
    statuses = get_statuses(staff_ids)
    return [user_id for user_id, status in statuses.items() if status == STATUS_AVAILABLE]


def accepting_agents(user_ids=None):
    candidate_ids = available_agent_ids() if user_ids is None else list(user_ids)
    if not candidate_ids:
        return []
    agents = User.objects.filter(
        pk__in=candidate_ids, is_active=True, role__in=STAFF_ROLES
    ).annotate(open_chats=Count("assigned_tickets", filter=OPEN_CHAT_FILTER))
    return [agent for agent in agents if agent.open_chats < agent.max_concurrent_chats]


def online_agents():
    agents = list(
        User.objects.filter(is_active=True, role__in=STAFF_ROLES)
        .annotate(open_chats=Count("assigned_tickets", filter=OPEN_CHAT_FILTER))
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
