from datetime import datetime, time

from django.db.models import Q
from django.utils import timezone

from accounts.models import UserEvent
from audit.cursors import KINDS, TICKET_KIND, USER_KIND, encode_cursor
from tickets.models import TicketEvent

AUDIT_PAGE_SIZE = 50
SENSITIVE_FIELDS = frozenset({"password"})
MODELS = {TICKET_KIND: TicketEvent, USER_KIND: UserEvent}


def _within_dates(queryset, date_from, date_to):
    zone = timezone.get_current_timezone()
    if date_from is not None:
        start = datetime.combine(date_from, time.min, tzinfo=zone)
        queryset = queryset.filter(created_at__gte=start)
    if date_to is not None:
        end = datetime.combine(date_to, time.max, tzinfo=zone)
        queryset = queryset.filter(created_at__lte=end)
    return queryset


def _after(kind, cursor):
    moment, cursor_kind, cursor_id = cursor
    condition = Q(created_at__lt=moment)
    if kind == cursor_kind:
        condition |= Q(created_at=moment, pk__lt=cursor_id)
    elif kind < cursor_kind:
        condition |= Q(created_at=moment)
    return condition


def _filtered(kind, filters, cursor):
    queryset = MODELS[kind].objects.select_related("actor")
    actor = filters.get("actor")
    if actor is not None:
        queryset = queryset.filter(actor_id=actor)
    field_changed = filters.get("field_changed")
    if field_changed:
        queryset = queryset.filter(field_changed=field_changed)
    queryset = _within_dates(queryset, filters.get("date_from"), filters.get("date_to"))
    if cursor is not None:
        queryset = queryset.filter(_after(kind, cursor))
    return queryset


def _row(kind, event):
    sensitive = event.field_changed in SENSITIVE_FIELDS
    return {
        "id": event.pk,
        "kind": kind,
        "ticket": event.ticket_id if kind == TICKET_KIND else None,
        "user": event.user_id if kind == USER_KIND else None,
        "actor": event.actor_id,
        "actor_username": event.actor.username if event.actor_id else None,
        "field_changed": event.field_changed,
        "old_value": "" if sensitive else event.old_value,
        "new_value": "" if sensitive else event.new_value,
        "created_at": event.created_at,
    }


def _sort_key(row):
    return (row["created_at"], row["kind"], row["id"])


def audit_page(filters, cursor=None, page_size=AUDIT_PAGE_SIZE):
    kind = filters.get("kind")
    kinds = (kind,) if kind else KINDS
    rows = []
    for current in kinds:
        queryset = _filtered(current, filters, cursor).order_by("-created_at", "-id")
        rows.extend(_row(current, event) for event in queryset[: page_size + 1])
    rows.sort(key=_sort_key, reverse=True)
    page = rows[:page_size]
    next_cursor = None
    if len(rows) > page_size:
        last = page[-1]
        next_cursor = encode_cursor(last["created_at"], last["kind"], last["id"])
    return page, next_cursor
