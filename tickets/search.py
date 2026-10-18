from django.db.models import Q

from core.search import build_search_query, build_search_vector, normalize_search_text
from tickets.models import COMMENT_SEARCH_FIELDS, TICKET_SEARCH_FIELDS, Comment, Ticket


def search_tickets(queryset, term, include_internal):
    if not normalize_search_text(term):
        return queryset.none()
    query = build_search_query(term)

    ticket_vector = build_search_vector(*TICKET_SEARCH_FIELDS)
    ticket_ids = Ticket.all_objects.alias(search=ticket_vector).filter(search=query).values("pk")

    comments = Comment.objects.filter(kind=Comment.Kind.MESSAGE)
    if not include_internal:
        comments = comments.filter(is_internal=False)
    comment_vector = build_search_vector(*COMMENT_SEARCH_FIELDS)
    comment_ids = comments.alias(search=comment_vector).filter(search=query).values("ticket_id")

    return queryset.filter(Q(pk__in=ticket_ids) | Q(pk__in=comment_ids))
