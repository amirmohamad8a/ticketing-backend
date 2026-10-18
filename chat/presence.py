from django.conf import settings
from django.core.cache import cache

from accounts.models import User
from accounts.permissions import STAFF_ROLES
from tickets.selectors import annotate_open_chats

CACHE_PREFIX = "presence:"
STATUS_AVAILABLE = "available"
STATUS_AWAY = "away"
STATUSES = (STATUS_AVAILABLE, STATUS_AWAY)


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


def _staff_statuses():
    staff_ids = list(
        User.objects.filter(is_active=True, role__in=STAFF_ROLES).values_list("pk", flat=True)
    )
    return get_statuses(staff_ids)


def online_agent_ids():
    return list(_staff_statuses())


def available_agent_ids():
    return [user_id for user_id, status in _staff_statuses().items() if status == STATUS_AVAILABLE]


def accepting_agents(user_ids=None):
    candidate_ids = available_agent_ids() if user_ids is None else list(user_ids)
    if not candidate_ids:
        return []
    agents = annotate_open_chats(
        User.objects.filter(pk__in=candidate_ids, is_active=True, role__in=STAFF_ROLES)
    )
    return [agent for agent in agents if agent.open_chats < agent.max_concurrent_chats]


def online_agents():
    agents = list(
        annotate_open_chats(User.objects.filter(is_active=True, role__in=STAFF_ROLES)).order_by(
            "first_name", "last_name", "username", "id"
        )
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
