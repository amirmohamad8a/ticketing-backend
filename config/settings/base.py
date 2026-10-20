from django.core.exceptions import ImproperlyConfigured

from config.settings.celery import *
from config.settings.environment import env
from config.settings.jwt import *
from config.settings.logging import *
from config.settings.realtime import *
from config.settings.redis import *
from config.settings.security import *
from config.settings.storage import *
from config.settings.throttling import *
from config.settings.widget import *

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "channels",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "accounts",
    "tickets",
    "chat",
    "realtime",
    "stats",
    "audit",
    "core",
]

MIDDLEWARE = [
    "core.middleware.RequestIdMiddleware",
    "core.metrics.RequestMetricsMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "core.middleware.RequestSizeLimitMiddleware",
    "core.middleware.AdminLoginThrottleMiddleware",
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


DATABASE_URL = env("DATABASE_URL", default="")
if not DATABASE_URL:
    raise ImproperlyConfigured("DATABASE_URL must be set.")
if not DATABASE_URL.startswith(("postgres://", "postgresql://")):
    raise ImproperlyConfigured("DATABASE_URL must point to PostgreSQL.")

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = 60
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = ["accounts.backends.CaseInsensitiveModelBackend"]


SPECTACULAR_SETTINGS = {
    "TITLE": "Ticketing API",
    "DESCRIPTION": (
        "Support ticketing system API: tickets, comments, attachments, the chat widget, "
        "agent presence, statistics and the audit trail.\n\n"
        "Staff and customers authenticate with `Authorization: Bearer <access token>`. "
        "Widget visitors authenticate with the `X-Visitor-Token` header and must call "
        "from an origin listed in the site's `allowed_origins`.\n\n"
        "Every failed request returns the same envelope: "
        '`{"error": {"code": "...", "message": "...", "details": ...}}`. '
        "`details` holds the field errors of a validation error and is `null` otherwise. "
        "Clients should branch on `code` and never display `message`.\n\n"
        "WebSocket messages are not part of OpenAPI. They are described in "
        "`docs/realtime.md`."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "COMPONENT_SPLIT_REQUEST": True,
    "TAGS": [
        {
            "name": "Auth",
            "description": "Registration, login, logout, profile and password change.",
        },
        {"name": "Users", "description": "User management for admins."},
        {
            "name": "Agents",
            "description": "Agent lists for assignment and live presence.",
        },
        {"name": "Avatars", "description": "Signed download links for avatars."},
        {
            "name": "Tickets",
            "description": (
                "Tickets, messages, comments, attachments, ratings and events. "
                "Customers receive a reduced ticket without `tags` and "
                "`first_response_due_at`."
            ),
        },
        {"name": "Attachments", "description": "Signed download links for attachments."},
        {"name": "Canned replies", "description": "Reply templates for agents."},
        {"name": "Tags", "description": "Ticket tags."},
        {"name": "Sites", "description": "Chat sites and widget settings for admins."},
        {"name": "Widget", "description": "Public API used by the embeddable chat widget."},
        {"name": "Realtime", "description": "HTTP side of the WebSocket layer."},
        {"name": "Stats", "description": "Support metrics."},
        {"name": "Audit", "description": "Ticket and user audit trail for admins."},
    ],
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "core.schema.add_error_responses",
    ],
    "ENUM_NAME_OVERRIDES": {
        "TicketStatusEnum": "tickets.models.Ticket.Status",
        "PresenceStatusEnum": "chat.presence.STATUSES",
        "KindEnum": "tickets.models.Comment.Kind",
        "AuditKindEnum": "audit.cursors.KINDS",
    },
}

API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=True)


LANGUAGE_CODE = "fa"

TIME_ZONE = "Asia/Tehran"

USE_I18N = True

USE_TZ = True


SLA_FIRST_RESPONSE_MINUTES = {
    "low": env.int("SLA_FIRST_RESPONSE_LOW_MINUTES", default=1440),
    "medium": env.int("SLA_FIRST_RESPONSE_MEDIUM_MINUTES", default=480),
    "high": env.int("SLA_FIRST_RESPONSE_HIGH_MINUTES", default=240),
    "urgent": env.int("SLA_FIRST_RESPONSE_URGENT_MINUTES", default=60),
}

AUTO_CLOSE_AFTER_DAYS = env.int("AUTO_CLOSE_AFTER_DAYS", default=7)
VISITOR_RETENTION_DAYS = env.int("VISITOR_RETENTION_DAYS", default=30)
