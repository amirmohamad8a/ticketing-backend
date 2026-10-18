from datetime import timedelta

from django.conf import settings
from django.utils import timezone

import jwt

TOKEN_KIND = "visitor"
ALGORITHM = "HS256"
KEY_SUFFIX = ":chat.visitor"


class InvalidVisitorToken(Exception):
    pass


def _signing_key():
    return f"{settings.JWT_SIGNING_KEY}{KEY_SUFFIX}"


def _is_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def issue_visitor_token(visitor):
    now = timezone.now()
    payload = {
        "kind": TOKEN_KIND,
        "visitor_id": visitor.pk,
        "site_id": visitor.site_id,
        "iat": now,
        "exp": now + timedelta(days=settings.VISITOR_TOKEN_LIFETIME_DAYS),
    }
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


def decode_visitor_token(token):
    if not isinstance(token, str) or not token:
        raise InvalidVisitorToken
    try:
        payload = jwt.decode(
            token,
            _signing_key(),
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat"]},
        )
    except jwt.InvalidTokenError:
        raise InvalidVisitorToken from None
    if payload.get("kind") != TOKEN_KIND:
        raise InvalidVisitorToken
    visitor_id = payload.get("visitor_id")
    site_id = payload.get("site_id")
    if not (_is_id(visitor_id) and _is_id(site_id)):
        raise InvalidVisitorToken
    return visitor_id, site_id
