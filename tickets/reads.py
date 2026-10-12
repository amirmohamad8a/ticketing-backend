from django.db.models import BigIntegerField, Count, IntegerField, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import ValidationError

from accounts.models import User
from tickets.models import Comment, ConversationRead


def _reader_filter(user, visitor):
    if (user is None) == (visitor is None):
        raise ValueError("A reader needs exactly one of user or visitor.")
    return {"user": user} if user is not None else {"visitor": visitor}


def visible_comments(ticket, user=None, visitor=None):
    _reader_filter(user, visitor)
    queryset = Comment.objects.filter(ticket=ticket)
    if visitor is not None or user.role == User.Role.CUSTOMER:
        return queryset.filter(is_internal=False)
    return queryset


def _comments_from_others(ticket, user, visitor):
    queryset = visible_comments(ticket, user, visitor)
    if visitor is not None:
        return queryset.exclude(visitor=visitor)
    return queryset.exclude(author=user)


def _last_read(ticket, user, visitor):
    return (
        ConversationRead.objects.filter(ticket=ticket, **_reader_filter(user, visitor))
        .values_list("last_read_comment_id", flat=True)
        .first()
        or 0
    )


def read_state(ticket, user=None, visitor=None):
    last_read = _last_read(ticket, user, visitor)
    unread = _comments_from_others(ticket, user, visitor).filter(id__gt=last_read).count()
    return {"last_read_comment_id": last_read, "unread_count": unread}


def unread_count(ticket, user=None, visitor=None):
    return read_state(ticket, user, visitor)["unread_count"]


def mark_conversation_read(ticket, comment_id=None, user=None, visitor=None):
    reader = _reader_filter(user, visitor)
    visible = visible_comments(ticket, user, visitor)
    if comment_id is None:
        comment_id = visible.aggregate(latest=Max("id"))["latest"] or 0
    elif not visible.filter(pk=comment_id).exists():
        raise ValidationError(
            {"last_read_comment_id": _("This message does not exist in this conversation.")}
        )
    record, _created = ConversationRead.objects.get_or_create(ticket=ticket, **reader)
    ConversationRead.objects.filter(pk=record.pk, last_read_comment_id__lt=comment_id).update(
        last_read_comment_id=comment_id, updated_at=timezone.now()
    )
    return read_state(ticket, user, visitor)


def annotate_unread(queryset, user):
    last_read = ConversationRead.objects.filter(ticket=OuterRef("pk"), user=user).values(
        "last_read_comment_id"
    )[:1]
    queryset = queryset.annotate(
        last_read_id=Coalesce(Subquery(last_read), 0, output_field=BigIntegerField())
    )
    comments = Comment.objects.filter(
        ticket=OuterRef("pk"), id__gt=OuterRef("last_read_id")
    ).exclude(author=user)
    if user.role == User.Role.CUSTOMER:
        comments = comments.filter(is_internal=False)
    counts = comments.order_by().values("ticket").annotate(total=Count("pk")).values("total")
    return queryset.annotate(
        unread_count=Coalesce(Subquery(counts, output_field=IntegerField()), 0)
    )
