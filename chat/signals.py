from django.dispatch import receiver

from tickets.models import Ticket
from tickets.signals import tickets_released


@receiver(tickets_released)
def reroute_released_chat_tickets(sender, tickets, **kwargs):
    from chat.assignment import route_new_chat

    for ticket in tickets:
        if ticket.channel == Ticket.Channel.CHAT:
            route_new_chat(ticket)
