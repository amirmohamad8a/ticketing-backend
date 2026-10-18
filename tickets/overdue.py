from tickets.models import Ticket


def overdue_ticket_ids(now=None):
    return Ticket.all_objects.overdue(now).values("pk")


def filter_overdue(queryset, overdue=True, now=None):
    ids = overdue_ticket_ids(now)
    if overdue:
        return queryset.filter(pk__in=ids)
    return queryset.exclude(pk__in=ids)
