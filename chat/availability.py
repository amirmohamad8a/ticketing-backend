from django.conf import settings
from django.core.cache import cache

from chat import presence

CACHE_KEY = "chat:agents-available"
DEFAULT_CACHE_SECONDS = 5


def agents_available():
    ttl = getattr(settings, "AGENTS_AVAILABLE_CACHE_SECONDS", DEFAULT_CACHE_SECONDS)
    if ttl <= 0:
        return bool(presence.accepting_agents())
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    result = bool(presence.accepting_agents())
    cache.set(CACHE_KEY, result, timeout=ttl)
    return result
