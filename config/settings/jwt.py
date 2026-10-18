from datetime import timedelta

from config.settings.environment import env
from config.settings.security import SECRET_KEY

JWT_SIGNING_KEY = env("JWT_SIGNING_KEY", default=SECRET_KEY)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "SIGNING_KEY": JWT_SIGNING_KEY,
    "CHECK_REVOKE_TOKEN": True,
}

VISITOR_TOKEN_LIFETIME_DAYS = env.int("VISITOR_TOKEN_LIFETIME_DAYS", default=30)
