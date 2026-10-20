import logging
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext

from accounts.permissions import STAFF_ROLES
from chat import presence
from chat.assignment import route_queued_chats
from core.events import OFFLINE_EVENT_TYPE, publish
from tickets.events import TicketEventField, record_event
from tickets.messages import post_message
from tickets.models import Comment, Ticket, TicketEvent

logger = logging.getLogger(__name__)

CHANNEL_FIELD = TicketEventField.CHANNEL
EARLY_CANDIDATES_KEY = "chat:offline-early-candidates"
EARLY_CANDIDATES_TTL_SECONDS = 180


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
        "We could not reach an agent in time. Leave your contact details and we will get back "
        "to you."
    )


def _unanswered_chats():
    return Ticket.objects.chat().unfinished().filter(~Exists(_public_staff_replies(OuterRef("pk"))))


def _waiting_since():
    latest_assignment = (
        TicketEvent.objects.filter(ticket=OuterRef("pk"), field_changed=TicketEventField.ASSIGNEE)
        .order_by("-created_at", "-pk")
        .values("created_at")[:1]
    )
    return Coalesce(Subquery(latest_assignment), F("created_at"))


def _online_assignee_within_timeout(ticket, now):
    if ticket.assignee_id is None or ticket.assignee_id not in presence.online_agent_ids():
        return False
    waiting_since = (
        Ticket.objects.annotate(waiting_since=_waiting_since())
        .values_list("waiting_since", flat=True)
        .get(pk=ticket.pk)
    )
    timeout = ticket.site.offline_timeout_minutes if ticket.site_id else 0
    return waiting_since + timedelta(minutes=timeout) > now


class EarlyCandidateConfirmation:
    def __init__(self, key=EARLY_CANDIDATES_KEY, ttl_seconds=EARLY_CANDIDATES_TTL_SECONDS):
        self.key = key
        self.ttl_seconds = ttl_seconds

    def confirm(self, candidate_ids):
        candidate_ids = set(candidate_ids)
        previous = set(cache.get(self.key) or ())
        cache.set(self.key, list(candidate_ids), timeout=self.ttl_seconds)
        return previous.intersection(candidate_ids)


EARLY_CANDIDATES = EarlyCandidateConfirmation()


def due_chat_ticket_ids(now=None):
    now = now or timezone.now()
    online_ids = set(presence.online_agent_ids())
    nobody_online = not online_ids
    rows = list(
        _unanswered_chats()
        .annotate(waiting_since=_waiting_since())
        .order_by("created_at", "pk")
        .values_list("pk", "waiting_since", "site__offline_timeout_minutes", "assignee_id")
    )
    expired = set()
    early = set()
    for pk, waiting_since, timeout, assignee_id in rows:
        if waiting_since + timedelta(minutes=timeout or 0) <= now:
            expired.add(pk)
        elif assignee_id is None:
            if nobody_online:
                early.add(pk)
        elif assignee_id not in online_ids:
            early.add(pk)
    due = expired | EARLY_CANDIDATES.confirm(early)
    return [pk for pk, *_rest in rows if pk in due]


def convert_unanswered_chat(ticket_id):
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(pk=ticket_id).first()
        if ticket is None or ticket.channel != Ticket.Channel.CHAT:
            return False
        if ticket.status in Ticket.FINISHED_STATUSES or _agent_replied(ticket):
            return False
        if _online_assignee_within_timeout(ticket, timezone.now()):
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
    drained = route_queued_chats()
    if converted or drained:
        logger.info(
            "Offline sweep finished",
            extra={"converted": converted, "drained": drained},
        )
    return converted
