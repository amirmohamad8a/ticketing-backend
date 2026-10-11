from django.utils.translation import gettext_lazy as _

import django_filters
from rest_framework.exceptions import ValidationError

from tickets.models import Ticket


class TicketFilter(django_filters.FilterSet):
    assignee = django_filters.CharFilter(method="filter_assignee")

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
