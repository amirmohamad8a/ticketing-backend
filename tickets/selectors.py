from django.db.models import Count, Q

from accounts.models import User
from tickets.models import Attachment, Ticket
from tickets.participants import Participant


def annotate_open_chats(queryset):
    open_chat_filter = Q(
        assigned_tickets__channel=Ticket.Channel.CHAT,
        assigned_tickets__is_deleted=False,
    ) & ~Q(assigned_tickets__status__in=Ticket.FINISHED_STATUSES)
    return queryset.annotate(open_chats=Count("assigned_tickets", filter=open_chat_filter))


def comment_visibility_filter(participant: Participant):
    if participant.sees_internal_notes:
        return Q()
    return Q(is_internal=False)


def unread_comment_filter(participant: Participant):
    visibility = comment_visibility_filter(participant)
    if participant.is_visitor:
        return visibility & ~Q(visitor=participant.visitor)
    return visibility & ~Q(author=participant.user)


def visible_attachments(viewer, queryset=None):
    queryset = Attachment.objects.all() if queryset is None else queryset
    role = getattr(viewer, "role", None)
    if role == User.Role.CUSTOMER:
        ticket_scope = Q(ticket__is_deleted=False, ticket__customer=viewer, is_internal=False)
        comment_scope = Q(
            comment__ticket__is_deleted=False,
            comment__ticket__customer=viewer,
            comment__is_internal=False,
        )
        return queryset.filter(ticket_scope | comment_scope)
    if role is None:
        return queryset.filter(
            comment__ticket__visitor=viewer,
            comment__ticket__is_deleted=False,
            comment__is_internal=False,
        )
    return queryset.filter(Q(ticket__is_deleted=False) | Q(comment__ticket__is_deleted=False))
