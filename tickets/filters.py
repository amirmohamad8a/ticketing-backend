from django.utils.translation import gettext_lazy as _

import django_filters
from django_filters.widgets import BooleanWidget
from rest_framework.exceptions import ValidationError

from accounts.permissions import STAFF_ROLES
from core.search import MAX_SEARCH_LENGTH
from tickets.models import Ticket
from tickets.overdue import filter_overdue
from tickets.search import search_tickets


def _is_staff(request):
    user = getattr(request, "user", None)
    return getattr(user, "role", None) in STAFF_ROLES


class TicketFilter(django_filters.FilterSet):
    assignee = django_filters.CharFilter(method="filter_assignee")
    tag = django_filters.CharFilter(
        method="filter_tag",
        help_text=_("Filter by tag id."),
    )
    is_overdue = django_filters.BooleanFilter(
        method="filter_is_overdue",
        widget=BooleanWidget,
        help_text=_("Tickets past their first-response deadline that no agent has answered."),
    )
    search = django_filters.CharFilter(
        method="filter_search",
        max_length=MAX_SEARCH_LENGTH,
        help_text=_("Search ticket titles, descriptions and messages."),
    )

    class Meta:
        model = Ticket
        fields = ["status", "priority", "channel"]

    def filter_assignee(self, queryset, name, value):
        if value == "me":
            if not self.request or not self.request.user.is_authenticated:
                return queryset.none()
            return queryset.filter(assignee=self.request.user)
        if not (value.isascii() and value.isdigit()):
            raise ValidationError({"assignee": _("Must be 'me' or a numeric user id.")})
        return queryset.filter(assignee_id=int(value))

    def filter_tag(self, queryset, name, value):
        if not (value.isascii() and value.isdigit()):
            raise ValidationError({"tag": _("Must be a numeric tag id.")})
        if not _is_staff(self.request):
            return queryset.none()
        return queryset.filter(tags__pk=int(value))

    def filter_is_overdue(self, queryset, name, value):
        if not _is_staff(self.request):
            return queryset.none()
        return filter_overdue(queryset, overdue=value)

    def filter_search(self, queryset, name, value):
        user = getattr(self.request, "user", None)
        role = getattr(user, "role", None)
        return search_tickets(queryset, value, role in STAFF_ROLES)
