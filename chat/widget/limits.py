from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from rest_framework.exceptions import Throttled

from tickets.models import Ticket

WINDOW_SECONDS = 3600
RETRY_AFTER_SECONDS = 60


def _count_start(site):
    key = f"widget-site-starts:{site.pk}"
    cache.add(key, 0, timeout=WINDOW_SECONDS)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=WINDOW_SECONDS)
        return 1


def _unassigned_chats(site):
    window_start = timezone.now() - timedelta(
        minutes=settings.WIDGET_SITE_UNASSIGNED_WINDOW_MINUTES
    )
    return (
        Ticket.objects.filter(site=site, created_at__gte=window_start)
        .chat()
        .unassigned()
        .unfinished()
        .count()
    )


def ensure_site_capacity(site):
    if _unassigned_chats(site) >= settings.WIDGET_SITE_MAX_UNASSIGNED_CHATS:
        raise Throttled(wait=RETRY_AFTER_SECONDS)
    if _count_start(site) > settings.WIDGET_SITE_START_LIMIT_PER_HOUR:
        raise Throttled(wait=RETRY_AFTER_SECONDS)
