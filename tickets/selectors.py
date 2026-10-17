from django.db.models import Count, Q

from tickets.models import Ticket


def annotate_open_chats(queryset):
    open_chat_filter = Q(
        assigned_tickets__channel=Ticket.Channel.CHAT,
        assigned_tickets__is_deleted=False,
    ) & ~Q(assigned_tickets__status__in=Ticket.FINISHED_STATUSES)
    return queryset.annotate(open_chats=Count("assigned_tickets", filter=open_chat_filter))
