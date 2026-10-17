import hashlib
import secrets

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import ValidationError

SALT = "chat.widget.pow"
USED_PREFIX = "widget-pow-used:"


def _invalid():
    return ValidationError(
        {"pow_challenge": _("The proof of work is missing, invalid or expired.")}
    )


def issue_challenge(site):
    difficulty = settings.WIDGET_POW_DIFFICULTY
    if difficulty <= 0:
        return {"challenge": None, "difficulty": 0, "expires_in": 0}
    token = signing.dumps(
        {"site": site.pk, "salt": secrets.token_hex(16), "bits": difficulty},
        salt=SALT,
    )
    return {
        "challenge": token,
        "difficulty": difficulty,
        "expires_in": settings.WIDGET_POW_TTL_SECONDS,
    }


def _leading_zero_bits(digest):
    return len(digest) * 8 - int.from_bytes(digest, "big").bit_length()


def verify_solution(site, challenge, nonce):
    if settings.WIDGET_POW_DIFFICULTY <= 0:
        return
    if not challenge or not nonce:
        raise _invalid()
    ttl = settings.WIDGET_POW_TTL_SECONDS
    try:
        payload = signing.loads(challenge, salt=SALT, max_age=ttl)
    except signing.BadSignature:
        raise _invalid()
    if payload.get("site") != site.pk or payload.get("bits", 0) < settings.WIDGET_POW_DIFFICULTY:
        raise _invalid()
    digest = hashlib.sha256(f"{challenge}:{nonce}".encode("utf-8")).digest()
    if _leading_zero_bits(digest) < payload["bits"]:
        raise _invalid()
    used_key = USED_PREFIX + hashlib.sha256(challenge.encode("utf-8")).hexdigest()
    if not cache.add(used_key, 1, timeout=ttl):
        raise _invalid()
