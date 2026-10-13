from datetime import datetime, time, timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F
from django.db.models.functions import TruncDate
from django.utils import timezone

from accounts.models import User
from accounts.permissions import STAFF_ROLES
from realtime.presence import OPEN_CHAT_FILTER
from tickets.models import Ticket


def _bounds(date_from, date_to):
    zone = timezone.get_current_timezone()
    start = datetime.combine(date_from, time.min, tzinfo=zone)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=zone)
    return start, end


def _elapsed_since_creation(field_name):
    return ExpressionWrapper(F(field_name) - F("created_at"), output_field=DurationField())


def _seconds(value):
    if value is None:
        return None
    return round(value.total_seconds(), 1)


def _queue_size():
    return (
        Ticket.objects.filter(assignee__isnull=True)
        .exclude(status__in=Ticket.FINISHED_STATUSES)
        .count()
    )


def _open_chats_per_agent():
    agents = (
        User.objects.filter(is_active=True, role__in=STAFF_ROLES)
        .annotate(open_chats=Count("assigned_tickets", filter=OPEN_CHAT_FILTER))
        .order_by("first_name", "last_name", "username", "id")
    )
    return [
        {
            "id": agent.pk,
            "name": agent.get_full_name() or agent.username,
            "open_chats": agent.open_chats,
        }
        for agent in agents
    ]


def _tickets_per_day(tickets, date_from, date_to):
    rows = (
        tickets.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("pk"))
        .order_by("day")
    )
    counts = {row["day"]: row["count"] for row in rows}
    total_days = (date_to - date_from).days + 1
    days = (date_from + timedelta(days=offset) for offset in range(total_days))
    return [{"date": day, "count": counts.get(day, 0)} for day in days]


def _tickets_per_channel(tickets):
    rows = tickets.values("channel").annotate(count=Count("pk")).order_by()
    counts = {row["channel"]: row["count"] for row in rows}
    return [
        {"channel": channel, "count": counts.get(channel, 0)} for channel in Ticket.Channel.values
    ]


def build_stats(date_from, date_to):
    start, end = _bounds(date_from, date_to)
    tickets = Ticket.objects.filter(created_at__gte=start, created_at__lt=end)
    totals = tickets.aggregate(
        total=Count("pk"),
        first_response=Avg(_elapsed_since_creation("first_response_at")),
        resolution=Avg(_elapsed_since_creation("resolved_at")),
    )
    return {
        "range": {"date_from": date_from, "date_to": date_to},
        "queue_size": _queue_size(),
        "open_chats_per_agent": _open_chats_per_agent(),
        "average_first_response_seconds": _seconds(totals["first_response"]),
        "average_resolution_seconds": _seconds(totals["resolution"]),
        "tickets_total": totals["total"],
        "tickets_per_day": _tickets_per_day(tickets, date_from, date_to),
        "tickets_per_channel": _tickets_per_channel(tickets),
    }
