from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import AgentFactory, TicketFactory, UserFactory
from tickets.filters import TicketFilter
from tickets.models import Ticket


def _auth(client, user):
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class TicketFilterTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = UserFactory()
        self.other_customer = UserFactory()
        self.agent = AgentFactory()
        self.other_agent = AgentFactory()
        self.open_high = TicketFactory(
            customer=self.customer,
            status=Ticket.Status.OPEN,
            priority=Ticket.Priority.HIGH,
            assignee=self.agent,
        )
        self.progress_high = TicketFactory(
            customer=self.customer,
            status=Ticket.Status.IN_PROGRESS,
            priority=Ticket.Priority.HIGH,
            assignee=self.other_agent,
        )
        self.open_low = TicketFactory(
            customer=self.customer,
            status=Ticket.Status.OPEN,
            priority=Ticket.Priority.LOW,
        )
        self.foreign_open_high = TicketFactory(
            customer=self.other_customer,
            status=Ticket.Status.OPEN,
            priority=Ticket.Priority.HIGH,
            assignee=self.agent,
        )

    def _assert_result(self, user, query, expected):
        _auth(self.client, user)
        response = self.client.get(f"/api/tickets/{query}")
        self.assertEqual(response.status_code, 200)
        ids = {ticket["id"] for ticket in response.data["results"]}
        self.assertEqual(ids, {ticket.id for ticket in expected})

    def _assert_rejected(self, query, field):
        _auth(self.client, self.agent)
        response = self.client.get(f"/api/tickets/{query}")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])

    def test_status_filter(self):
        expected = [self.open_high, self.open_low, self.foreign_open_high]
        self._assert_result(self.agent, "?status=open", expected)

    def test_priority_filter(self):
        expected = [self.open_high, self.progress_high, self.foreign_open_high]
        self._assert_result(self.agent, "?priority=high", expected)

    def test_status_and_priority_filters_combine(self):
        expected = [self.open_high, self.foreign_open_high]
        self._assert_result(self.agent, "?status=open&priority=high", expected)

    def test_assignee_me_resolves_to_the_requesting_agent(self):
        expected = [self.open_high, self.foreign_open_high]
        self._assert_result(self.agent, "?assignee=me", expected)
        self._assert_result(self.other_agent, "?assignee=me", [self.progress_high])

    def test_status_priority_and_assignee_me_combine(self):
        query = "?status=open&priority=high&assignee=me"
        expected = [self.open_high, self.foreign_open_high]
        self._assert_result(self.agent, query, expected)

    def test_assignee_filter_by_user_id(self):
        query = f"?assignee={self.other_agent.id}"
        self._assert_result(self.agent, query, [self.progress_high])

    def test_assignee_unassigned_returns_only_tickets_without_an_assignee(self):
        extra = TicketFactory(customer=self.customer, assignee=None)
        expected = list(Ticket.objects.filter(assignee__isnull=True))
        self.assertIn(extra, expected)
        self.assertNotIn(self.open_high, expected)
        self._assert_result(self.agent, "?assignee=unassigned", expected)

    def test_assignee_rejects_other_words(self):
        _auth(self.client, self.agent)
        response = self.client.get("/api/tickets/?assignee=nobody")
        self.assertEqual(response.status_code, 400)
        self.assertIn("assignee", response.data["error"]["details"])

    def test_assignee_id_without_tickets_returns_an_empty_page(self):
        self._assert_result(self.agent, "?assignee=999999", [])

    def test_assignee_me_for_a_customer_returns_nothing(self):
        self._assert_result(self.customer, "?assignee=me", [])

    def test_customer_filters_stay_scoped_to_own_tickets(self):
        expected = [self.open_high, self.progress_high]
        self._assert_result(self.customer, "?priority=high", expected)

    def test_empty_assignee_param_is_ignored(self):
        self._assert_result(self.agent, "?assignee=", Ticket.objects.all())

    def test_unknown_param_is_ignored(self):
        self._assert_result(self.agent, "?unknown=1", Ticket.objects.all())

    def test_invalid_status_is_rejected(self):
        self._assert_rejected("?status=bogus", "status")

    def test_invalid_priority_is_rejected(self):
        self._assert_rejected("?priority=bogus", "priority")

    def test_non_numeric_assignee_is_rejected(self):
        self._assert_rejected("?assignee=abc", "assignee")

    def test_negative_and_decimal_assignee_are_rejected(self):
        self._assert_rejected("?assignee=-1", "assignee")
        self._assert_rejected("?assignee=1.5", "assignee")


class TicketFilterWithoutAuthenticatedUserTests(TestCase):
    def setUp(self):
        self.agent = AgentFactory()
        TicketFactory(assignee=self.agent)

    def _apply(self, request):
        data = {"assignee": "me"}
        queryset = Ticket.objects.all()
        return TicketFilter(data, queryset=queryset, request=request).qs

    def test_assignee_me_without_a_request_returns_nothing(self):
        self.assertEqual(self._apply(None).count(), 0)

    def test_assignee_me_for_an_anonymous_user_returns_nothing(self):
        request = SimpleNamespace(user=AnonymousUser())
        self.assertEqual(self._apply(request).count(), 0)

    def test_assignee_me_for_an_authenticated_user_returns_their_tickets(self):
        request = SimpleNamespace(user=self.agent)
        self.assertEqual(self._apply(request).count(), 1)
