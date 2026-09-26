import django_filters

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
        return queryset.filter(assignee_id=value)
