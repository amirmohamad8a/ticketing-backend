from datetime import timedelta

from config.settings.redis import REDIS_URL

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {
    "tickets-auto-close-resolved": {
        "task": "tickets.auto_close_resolved",
        "schedule": timedelta(hours=1),
    },
    "chat-purge-stale-visitors": {
        "task": "chat.purge_stale_visitors",
        "schedule": timedelta(days=1),
    },
    "chat-sweep-unanswered-chats": {
        "task": "chat.sweep_unanswered_chats",
        "schedule": timedelta(minutes=1),
    },
    "accounts-flush-expired-tokens": {
        "task": "accounts.flush_expired_tokens",
        "schedule": timedelta(days=1),
    },
    "tickets-report-orphan-files": {
        "task": "tickets.report_orphan_files",
        "schedule": timedelta(days=1),
    },
}
