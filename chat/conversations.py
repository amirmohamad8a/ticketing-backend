import hashlib
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import ValidationError

from chat import presence
from chat.assignment import route_new_chat
from chat.models import Visitor
from chat.tasks import convert_to_offline
from chat.tokens import issue_visitor_token
from chat.visitors import VisitorSession, start_visitor_session
from tickets.events import TicketEventField, record_event
from tickets.messages import post_customer_message
from tickets.models import Comment, Ticket
from tickets.participants import Participant

TITLE_MAX_LENGTH = 100
START_REPLAY_WINDOW = timedelta(minutes=10)


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


def _lock_start(site_id, client_msg_id):
    digest = hashlib.sha256(f"widget-start:{site_id}:{client_msg_id}".encode()).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def find_replayed_start(site, client_msg_id, body):
    if not client_msg_id:
        return None
    earlier = Comment.objects.filter(ticket=OuterRef("ticket"), id__lt=OuterRef("id"))
    comment = (
        Comment.objects.filter(
            visitor__site=site,
            client_msg_id=client_msg_id,
            kind=Comment.Kind.MESSAGE,
            ticket__created_at__gte=timezone.now() - START_REPLAY_WINDOW,
        )
        .exclude(Exists(earlier))
        .select_related("ticket", "visitor")
        .first()
    )
    if comment is None:
        return None
    if comment.body != body:
        raise ValidationError(
            {"client_msg_id": _("This client message ID is already used in this conversation.")}
        )
    return comment


def replay_session(comment):
    return VisitorSession(visitor=comment.visitor, token=issue_visitor_token(comment.visitor))


def start_or_replay(site, body, name="", phone="", email="", client_msg_id=None):
    with transaction.atomic():
        if client_msg_id:
            _lock_start(site.pk, client_msg_id)
            replay = find_replayed_start(site, client_msg_id, body)
            if replay is not None:
                return replay_session(replay), replay.ticket, replay, False
        session, ticket, comment = start_conversation(
            site, body, name=name, phone=phone, email=email, client_msg_id=client_msg_id
        )
    return session, ticket, comment, True


def start_conversation(site, body, name="", phone="", email="", client_msg_id=None):
    with transaction.atomic():
        session = start_visitor_session(site, name=name, phone=phone, email=email)
        ticket, comment, _created = open_conversation(session.visitor, body, client_msg_id)
    return session, ticket, comment
