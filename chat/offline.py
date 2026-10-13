from django.db import transaction
from django.utils.translation import gettext

from accounts.permissions import STAFF_ROLES
from chat.availability import agents_available
from realtime.events import publish
from tickets.events import record_event
from tickets.messages import post_message
from tickets.models import Comment, Ticket

OFFLINE_EVENT_TYPE = "conversation.offline"
CHANNEL_FIELD = "channel"


def fallback_countdown(site):
    if agents_available(site):
        return site.offline_timeout_minutes * 60
    return 0


def _agent_replied(ticket):
    return Comment.objects.filter(
        ticket=ticket,
        kind=Comment.Kind.MESSAGE,
        is_internal=False,
        author__role__in=STAFF_ROLES,
    ).exists()


def _offline_notice():
    return gettext(
        "No agent is available right now. Leave your contact details and we will get back to you."
    )


def convert_unanswered_chat(ticket_id):
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(pk=ticket_id).first()
        if ticket is None or ticket.channel != Ticket.Channel.CHAT:
            return False
        if ticket.status in Ticket.FINISHED_STATUSES or _agent_replied(ticket):
            return False
        old_channel = Ticket.Channel.CHAT.value
        ticket.channel = Ticket.Channel.OFFLINE_FORM
        ticket.save(update_fields=["channel", "updated_at"])
        event = record_event(
            ticket=ticket,
            actor=None,
            field_changed=CHANNEL_FIELD,
            old_value=old_channel,
            new_value=Ticket.Channel.OFFLINE_FORM.value,
        )
        post_message(ticket, _offline_notice(), kind=Comment.Kind.SYSTEM)
        visitor = ticket.visitor
        has_contact = bool(visitor is not None and (visitor.phone or visitor.email))
        publish(OFFLINE_EVENT_TYPE, event.pk, ticket.pk, {"has_contact": has_contact})
    return True
