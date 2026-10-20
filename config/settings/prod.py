import logging

from . import validation
from .base import *
from .validation import (
    resolve_num_proxies,
    validate_jwt_signing_key,
    validate_metrics_token,
    validate_secrets,
)

DEBUG = False

MIN_SECRET_LENGTH = validation.MIN_SECRET_LENGTH
EXAMPLE_SECRET_MARKER = validation.EXAMPLE_SECRET_MARKER
EXAMPLE_SECRET_PREFIX = validation.EXAMPLE_SECRET_PREFIX

JWT_SIGNING_KEY = env("JWT_SIGNING_KEY")
validate_jwt_signing_key(SECRET_KEY, JWT_SIGNING_KEY)

SIMPLE_JWT = {**SIMPLE_JWT, "SIGNING_KEY": JWT_SIGNING_KEY}

validate_secrets(SECRET_KEY=SECRET_KEY, JWT_SIGNING_KEY=JWT_SIGNING_KEY)
validate_metrics_token(METRICS_TOKEN)

ALLOW_ZERO_PROXIES = env.bool("ALLOW_ZERO_PROXIES", default=False)
NUM_PROXIES = resolve_num_proxies(
    env("NUM_PROXIES", default=None),
    ALLOW_ZERO_PROXIES,
    logging.getLogger(__name__),
)
REST_FRAMEWORK["NUM_PROXIES"] = NUM_PROXIES

WIDGET_POW_DIFFICULTY = env.int("WIDGET_POW_DIFFICULTY", default=18)

API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=False)
SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,
    "SERVE_PERMISSIONS": ["accounts.permissions.IsAdmin"],
}

_security_index = MIDDLEWARE.index("django.middleware.security.SecurityMiddleware")
MIDDLEWARE = [
    *MIDDLEWARE[: _security_index + 1],
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[_security_index + 1 :],
]

STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_REDIRECT_EXEMPT = [r"^health/$", r"^ready/$", r"^metrics/$"]
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
