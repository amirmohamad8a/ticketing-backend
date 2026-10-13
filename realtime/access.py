from channels.db import database_sync_to_async

from accounts.models import User
from chat.conversations import conversations_of
from tickets.models import Ticket


def visible_tickets(user=None, visitor=None):
    if visitor is not None:
        return conversations_of(visitor)
    queryset = Ticket.objects.all()
    if user.role == User.Role.CUSTOMER:
        queryset = queryset.filter(customer=user)
    return queryset


@database_sync_to_async
def can_join_ticket(user, visitor, ticket_id):
    return visible_tickets(user, visitor).filter(pk=ticket_id).exists()
