from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

import environ
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(str(BASE_DIR / ".env"))


SECRET_KEY = env("SECRET_KEY")
JWT_SIGNING_KEY = env("JWT_SIGNING_KEY", default=SECRET_KEY)
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])


INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "accounts",
    "tickets",
    "chat",
    "realtime",
    "core",
]

MIDDLEWARE = [
    "core.middleware.RequestIdMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


DATABASES = {"default": env.db("DATABASE_URL", default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')}

AUTH_USER_MODEL = "accounts.User"


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("core.authentication.LoggedJWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "300/min",
        "login": "10/min",
        "register": "10/hour",
        "password_change": "5/hour",
        "user_management": "60/min",
        "site_management": "60/min",
        "download": "300/min",
        "ws_ticket": "30/min",
        "widget_ip": "120/min",
        "widget_visitor": "90/min",
        "widget_start": "20/hour",
        "widget_upload": "30/hour",
    },
    "NUM_PROXIES": env.int("NUM_PROXIES", default=0),
}

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

SPECTACULAR_SETTINGS = {
    "TITLE": "Ticketing API",
    "DESCRIPTION": "Support ticketing system API — tickets, comments, attachments, audit history.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_EXPOSE_HEADERS = ["X-Request-ID"]
CORS_ALLOW_HEADERS = (*default_headers, "x-visitor-token")


LANGUAGE_CODE = "fa"

TIME_ZONE = "Asia/Tehran"

USE_I18N = True

USE_TZ = True


STATIC_URL = "static/"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


STORAGE_BACKEND = env("STORAGE_BACKEND", default="local")
DOWNLOAD_URL_TTL_SECONDS = env.int("DOWNLOAD_URL_TTL_SECONDS", default=300)

if STORAGE_BACKEND == "local":
    _DEFAULT_STORAGE = {"BACKEND": "django.core.files.storage.FileSystemStorage"}
elif STORAGE_BACKEND == "s3":
    _DEFAULT_STORAGE = {
        "BACKEND": "core.storage.PresignedS3Storage",
        "OPTIONS": {
            "bucket_name": env("S3_BUCKET_NAME"),
            "access_key": env("S3_ACCESS_KEY"),
            "secret_key": env("S3_SECRET_KEY"),
            "endpoint_url": env("S3_ENDPOINT_URL", default=None),
            "public_endpoint_url": env("S3_PUBLIC_ENDPOINT_URL", default=None),
            "region_name": env("S3_REGION_NAME", default="us-east-1"),
            "signature_version": "s3v4",
            "addressing_style": "path",
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": DOWNLOAD_URL_TTL_SECONDS,
            "file_overwrite": False,
        },
    }
else:
    raise ImproperlyConfigured("STORAGE_BACKEND must be 'local' or 's3'.")

STORAGES = {
    "default": _DEFAULT_STORAGE,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "ticketing",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            "prefix": "ticketing",
        },
    }
}

WS_TICKET_TTL_SECONDS = env.int("WS_TICKET_TTL_SECONDS", default=30)
WS_MAX_MESSAGE_BYTES = env.int("WS_MAX_MESSAGE_BYTES", default=4096)
WS_RATE_LIMIT_MESSAGES = env.int("WS_RATE_LIMIT_MESSAGES", default=30)
WS_RATE_LIMIT_WINDOW_SECONDS = env.int("WS_RATE_LIMIT_WINDOW_SECONDS", default=10)

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True


LOG_LEVEL = env("LOG_LEVEL", default="INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "core.logs.JsonFormatter"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
        "null": {"class": "logging.NullHandler"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": [], "level": LOG_LEVEL, "propagate": True},
        "django.request": {"level": "ERROR"},
        "django.server": {"handlers": ["null"], "propagate": False},
    },
}
