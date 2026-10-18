import hashlib
import secrets

from django.conf import settings
from django.core.cache import cache

CACHE_PREFIX = "ws-ticket:"
MIN_TOKEN_LENGTH = 32
MAX_TOKEN_LENGTH = 128


def _cache_key(token):
    return CACHE_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_ticket(participant):
    if participant is None:
        raise ValueError("A ticket needs a participant.")
    if participant.is_visitor:
        payload = {"visitor_id": participant.visitor.pk}
    else:
        payload = {"user_id": participant.user.pk}
    token = secrets.token_urlsafe(32)
    ttl = settings.WS_TICKET_TTL_SECONDS
    cache.set(_cache_key(token), payload, timeout=ttl)
    return {"ticket": token, "expires_in": ttl}


def redeem_ticket(token):
    if not isinstance(token, str) or not MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH:
        return None
    key = _cache_key(token)
    payload = cache.get(key)
    if payload is None:
        return None
    if not cache.delete(key):
        return None
    return payload
