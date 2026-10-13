from django.db.models import Exists, OuterRef
from django.utils import timezone

from accounts.permissions import STAFF_ROLES
from tickets.models import Comment, Ticket


def _staff_replies():
    return Comment.objects.filter(
        ticket=OuterRef("pk"),
        kind=Comment.Kind.MESSAGE,
        is_internal=False,
        author__role__in=STAFF_ROLES,
    )


def overdue_ticket_ids(now=None):
    now = now or timezone.now()
    return (
        Ticket.all_objects.filter(first_response_due_at__lt=now)
        .exclude(status__in=Ticket.FINISHED_STATUSES)
        .filter(~Exists(_staff_replies()))
        .values("pk")
    )


def filter_overdue(queryset, overdue=True, now=None):
    ids = overdue_ticket_ids(now)
    if overdue:
        return queryset.filter(pk__in=ids)
    return queryset.exclude(pk__in=ids)
