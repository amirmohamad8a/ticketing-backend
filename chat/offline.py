import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.translation import gettext

from accounts.permissions import STAFF_ROLES
from chat.availability import any_agents_available
from realtime.events import publish
from tickets.events import record_event
from tickets.messages import post_message
from tickets.models import Comment, Ticket

logger = logging.getLogger(__name__)

OFFLINE_EVENT_TYPE = "conversation.offline"
CHANNEL_FIELD = "channel"


def _public_staff_replies(ticket):
    return Comment.objects.filter(
        ticket=ticket,
        kind=Comment.Kind.MESSAGE,
        is_internal=False,
        author__role__in=STAFF_ROLES,
    )


def _agent_replied(ticket):
    return _public_staff_replies(ticket).exists()


def _offline_notice():
    return gettext(
        "No agent is available right now. Leave your contact details and we will get back to you."
    )


def _unanswered_chats():
    return (
        Ticket.objects.filter(channel=Ticket.Channel.CHAT)
        .exclude(status__in=Ticket.FINISHED_STATUSES)
        .filter(~Exists(_public_staff_replies(OuterRef("pk"))))
    )


def due_chat_ticket_ids(now=None):
    now = now or timezone.now()
    nobody_online = not any_agents_available()
    rows = (
        _unanswered_chats()
        .order_by("created_at", "pk")
        .values_list("pk", "created_at", "site__offline_timeout_minutes")
    )
    return [
        pk
        for pk, created_at, timeout in rows
        if nobody_online or created_at + timedelta(minutes=timeout or 0) <= now
    ]


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


def convert_due_chats(now=None):
    converted = 0
    for ticket_id in due_chat_ticket_ids(now):
        try:
            if convert_unanswered_chat(ticket_id):
                converted += 1
        except Exception:
            logger.exception("Failed to convert an unanswered chat", extra={"ticket_id": ticket_id})
    if converted:
        logger.info("Offline sweep finished", extra={"converted": converted})
    return converted
