from django.db import transaction
from django.utils.text import Truncator

from chat import presence
from chat.assignment import route_new_chat
from chat.models import Visitor
from chat.tasks import convert_to_offline
from chat.visitors import start_visitor_session
from tickets.events import TicketEventField, record_event
from tickets.messages import post_customer_message
from tickets.models import Ticket
from tickets.participants import Participant

TITLE_MAX_LENGTH = 100


def conversations_of(visitor):
    return Ticket.objects.filter(visitor=visitor)


def active_conversation(visitor):
    return conversations_of(visitor).unfinished().order_by("-created_at", "-id").first()


def _schedule_offline_conversion(ticket):
    countdown = 0
    if presence.online_agent_ids():
        countdown = (ticket.site.offline_timeout_minutes if ticket.site_id else 0) * 60
    transaction.on_commit(
        lambda: convert_to_offline.apply_async(args=[ticket.pk], countdown=countdown),
        robust=True,
    )


def open_conversation(visitor, body, client_msg_id=None):
    with transaction.atomic():
        Visitor.objects.select_for_update().get(pk=visitor.pk)
        ticket = active_conversation(visitor)
        created = ticket is None
        if created:
            ticket = Ticket.objects.create(
                title=Truncator(" ".join(body.split())).chars(TITLE_MAX_LENGTH),
                description="",
                channel=Ticket.Channel.CHAT,
                site=visitor.site,
                visitor=visitor,
            )
            record_event(
                ticket=ticket,
                actor=None,
                field_changed=TicketEventField.CREATED,
                old_value="",
                new_value=ticket.status,
            )
        comment, _posted = post_customer_message(
            ticket,
            body,
            Participant(visitor=visitor),
            client_msg_id=client_msg_id,
        )
        if created and route_new_chat(ticket) is None:
            _schedule_offline_conversion(ticket)
    return ticket, comment, created


def start_conversation(site, body, name="", phone="", email="", client_msg_id=None):
    with transaction.atomic():
        session = start_visitor_session(site, name=name, phone=phone, email=email)
        ticket, comment, _created = open_conversation(session.visitor, body, client_msg_id)
    return session, ticket, comment
