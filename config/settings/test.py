from .dev import *

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        scope: "100000/min" for scope in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    },
}
