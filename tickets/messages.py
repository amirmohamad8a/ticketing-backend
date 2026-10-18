from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import ValidationError

from accounts.models import User
from accounts.permissions import STAFF_ROLES
from realtime.events import MESSAGE_EVENT_TYPE, publish
from tickets.lifecycle import reopen_on_customer_reply
from tickets.models import Comment, SenderType, Ticket

MESSAGES_PAGE_SIZE = 100


def comment_sender_type(comment):
    if comment.kind == Comment.Kind.SYSTEM:
        return SenderType.SYSTEM
    if comment.visitor_id:
        return SenderType.VISITOR
    if comment.author_id and comment.author.role == User.Role.CUSTOMER:
        return SenderType.CUSTOMER
    return SenderType.AGENT


def message_page(queryset, after, page_size):
    rows = list(queryset.filter(id__gt=after).order_by("id")[: page_size + 1])
    return rows[:page_size], len(rows) > page_size


def _find_existing(ticket, client_msg_id, author, visitor):
    return Comment.objects.filter(
        ticket=ticket,
        client_msg_id=client_msg_id,
        author=author,
        visitor=visitor,
    ).first()


def _publish_created(comment):
    publish(
        MESSAGE_EVENT_TYPE,
        comment.pk,
        comment.ticket_id,
        {
            "message_id": comment.pk,
            "kind": comment.kind,
            "sender_type": comment_sender_type(comment),
            "is_internal": comment.is_internal,
            "client_msg_id": comment.client_msg_id,
        },
        staff_only=comment.is_internal,
    )


def _is_public_staff_reply(comment):
    return (
        comment.kind == Comment.Kind.MESSAGE
        and not comment.is_internal
        and comment.author_id is not None
        and comment.author.role in STAFF_ROLES
    )


def _record_first_response(ticket, comment):
    if not _is_public_staff_reply(comment):
        return
    updated = Ticket.all_objects.filter(pk=ticket.pk, first_response_at__isnull=True).update(
        first_response_at=comment.created_at
    )
    if updated:
        ticket.first_response_at = comment.created_at


def post_message(
    ticket,
    body,
    author=None,
    visitor=None,
    is_internal=False,
    client_msg_id=None,
    kind=Comment.Kind.MESSAGE,
):
    if kind != Comment.Kind.SYSTEM and (author is None) == (visitor is None):
        raise ValueError("A message needs exactly one of author or visitor.")
    if visitor is not None:
        is_internal = False
    client_msg_id = client_msg_id or None

    if client_msg_id:
        existing = _find_existing(ticket, client_msg_id, author, visitor)
        if existing is not None:
            return existing, False

    try:
        with transaction.atomic():
            comment = Comment.objects.create(
                ticket=ticket,
                author=author,
                visitor=visitor,
                kind=kind,
                client_msg_id=client_msg_id,
                body=body,
                is_internal=is_internal,
            )
            _record_first_response(ticket, comment)
            _publish_created(comment)
    except IntegrityError:
        if not client_msg_id:
            raise
        existing = _find_existing(ticket, client_msg_id, author, visitor)
        if existing is not None:
            return existing, False
        if Comment.objects.filter(ticket=ticket, client_msg_id=client_msg_id).exists():
            raise ValidationError(
                {"client_msg_id": _("This client message ID is already used in this conversation.")}
            )
        raise
    return comment, True


def post_customer_message(
    ticket,
    body,
    actor=None,
    visitor=None,
    is_internal=False,
    client_msg_id=None,
    kind=Comment.Kind.MESSAGE,
    on_created=None,
):
    with transaction.atomic():
        comment, created = post_message(
            ticket,
            body,
            author=actor,
            visitor=visitor,
            is_internal=is_internal,
            client_msg_id=client_msg_id,
            kind=kind,
        )
        if created:
            if on_created is not None:
                on_created(comment)
            reopen_on_customer_reply(ticket.pk, actor=actor)
    return comment, created
