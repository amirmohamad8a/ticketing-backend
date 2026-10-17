import logging

from django.core.exceptions import ImproperlyConfigured

from .base import *

DEBUG = False

if env("LOADTEST_THROTTLE_RATES", default=""):
    raise ImproperlyConfigured("LOADTEST_THROTTLE_RATES must not be set in production.")

JWT_SIGNING_KEY = env("JWT_SIGNING_KEY")
if JWT_SIGNING_KEY == SECRET_KEY:
    raise ImproperlyConfigured("JWT_SIGNING_KEY must be different from SECRET_KEY.")

SIMPLE_JWT = {**SIMPLE_JWT, "SIGNING_KEY": JWT_SIGNING_KEY}

MIN_SECRET_LENGTH = 50
EXAMPLE_SECRET_MARKER = "change-me"
EXAMPLE_SECRET_PREFIX = "dev-"


def _is_example_secret(value):
    lowered = value.lower()
    return EXAMPLE_SECRET_MARKER in lowered or lowered.startswith(EXAMPLE_SECRET_PREFIX)


for _name, _value in (
    ("SECRET_KEY", SECRET_KEY),
    ("JWT_SIGNING_KEY", JWT_SIGNING_KEY),
):
    if _is_example_secret(_value):
        raise ImproperlyConfigured(f"{_name} is still an example value. Generate a real secret.")
    if len(_value) < MIN_SECRET_LENGTH:
        raise ImproperlyConfigured(f"{_name} must be at least {MIN_SECRET_LENGTH} characters long.")

if METRICS_TOKEN and _is_example_secret(METRICS_TOKEN):
    raise ImproperlyConfigured("METRICS_TOKEN is still an example value. Generate a real secret.")

if NUM_PROXIES == 0:
    logging.getLogger(__name__).warning(
        "NUM_PROXIES is 0. Behind a reverse proxy every client shares one throttle bucket "
        "and the client IP in the logs is the proxy address. Set NUM_PROXIES to the number "
        "of proxies in front of the app."
    )

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
