from channels.db import database_sync_to_async

from tickets.models import Ticket
from tickets.participants import Participant


def visible_tickets(participant: Participant):
    queryset = Ticket.objects.all()
    if participant.is_staff:
        return queryset
    return queryset.filter(**participant.ownership_filter)


@database_sync_to_async
def can_join_ticket(participant: Participant, ticket_id):
    return visible_tickets(participant).filter(pk=ticket_id).exists()
