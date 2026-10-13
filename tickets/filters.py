from django.utils.translation import gettext_lazy as _

import django_filters
from rest_framework.exceptions import ValidationError

from accounts.permissions import STAFF_ROLES
from core.search import MAX_SEARCH_LENGTH
from tickets.models import Ticket
from tickets.search import search_tickets


class TicketFilter(django_filters.FilterSet):
    assignee = django_filters.CharFilter(method="filter_assignee")
    search = django_filters.CharFilter(
        method="filter_search",
        max_length=MAX_SEARCH_LENGTH,
        help_text=_("Search ticket titles, descriptions and messages."),
    )

    class Meta:
        model = Ticket
        fields = ["status", "priority"]

    def filter_assignee(self, queryset, name, value):
        if value == "me":
            if not self.request or not self.request.user.is_authenticated:
                return queryset.none()
            return queryset.filter(assignee=self.request.user)
        if not (value.isascii() and value.isdigit()):
            raise ValidationError({"assignee": _("Must be 'me' or a numeric user id.")})
        return queryset.filter(assignee_id=int(value))

    def filter_search(self, queryset, name, value):
        user = getattr(self.request, "user", None)
        role = getattr(user, "role", None)
        return search_tickets(queryset, value, role in STAFF_ROLES)
