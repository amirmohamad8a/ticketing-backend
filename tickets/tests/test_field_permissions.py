from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import AdminFactory, AgentFactory, TicketFactory, UserFactory
from tickets.models import Ticket, TicketEvent
from tickets.serializers import CustomerTicketSerializer, TicketSerializer
from tickets.views import TicketViewSet


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class CustomerEditRuleTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.ticket = TicketFactory(
            customer=self.customer, title="Original", description="Original text"
        )
        self.url = f"/api/tickets/{self.ticket.id}/"
        self.client = _client_for(self.customer)

    def _staff_only_payloads(self):
        return {
            "status": Ticket.Status.IN_PROGRESS,
            "priority": Ticket.Priority.URGENT,
            "assignee": self.agent.id,
        }

    def _assert_ticket_untouched(self):
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.title, "Original")
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)
        self.assertEqual(self.ticket.priority, Ticket.Priority.MEDIUM)
        self.assertIsNone(self.ticket.assignee)
        self.assertFalse(TicketEvent.objects.filter(ticket=self.ticket).exists())

    def test_customer_can_edit_title_and_description_while_open(self):
        response = self.client.patch(self.url, {"title": "New title", "description": "New text"})
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.title, "New title")
        self.assertEqual(self.ticket.description, "New text")

    def test_customer_can_replace_title_and_description_with_put(self):
        response = self.client.put(self.url, {"title": "Put title", "description": "Put text"})
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.title, "Put title")

    def test_customer_cannot_change_staff_only_fields(self):
        for field, value in self._staff_only_payloads().items():
            with self.subTest(field=field):
                response = self.client.patch(self.url, {field: value})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["error"]["code"], "permission_denied")
                self._assert_ticket_untouched()

    def test_staff_only_field_is_refused_even_when_the_value_is_unchanged(self):
        for payload in ({"status": Ticket.Status.OPEN}, {"priority": Ticket.Priority.MEDIUM}):
            with self.subTest(payload=payload):
                response = self.client.patch(self.url, payload)
                self.assertEqual(response.status_code, 403)
                self._assert_ticket_untouched()

    def test_mixed_payload_is_refused_as_a_whole(self):
        response = self.client.patch(
            self.url, {"title": "Sneaky", "priority": Ticket.Priority.URGENT}
        )
        self.assertEqual(response.status_code, 403)
        self._assert_ticket_untouched()

    def test_put_with_a_staff_only_field_is_refused(self):
        response = self.client.put(
            self.url,
            {"title": "Put title", "description": "Put text", "status": Ticket.Status.OPEN},
        )
        self.assertEqual(response.status_code, 403)
        self._assert_ticket_untouched()

    def test_customer_cannot_edit_once_the_ticket_has_left_open(self):
        later_statuses = [
            Ticket.Status.IN_PROGRESS,
            Ticket.Status.WAITING_ON_CUSTOMER,
            Ticket.Status.RESOLVED,
            Ticket.Status.CLOSED,
        ]
        for status in later_statuses:
            with self.subTest(status=status):
                Ticket.objects.filter(pk=self.ticket.pk).update(status=status)
                response = self.client.patch(self.url, {"title": "Late edit"})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["error"]["code"], "permission_denied")
                self.ticket.refresh_from_db()
                self.assertEqual(self.ticket.title, "Original")

    def test_customer_can_still_comment_once_the_ticket_has_left_open(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(status=Ticket.Status.IN_PROGRESS)
        response = self.client.post(f"{self.url}comments/", {"body": "Still here."})
        self.assertEqual(response.status_code, 201)

    def test_another_customers_ticket_stays_hidden_before_the_field_check(self):
        client = _client_for(UserFactory())
        response = client.patch(self.url, {"status": Ticket.Status.IN_PROGRESS})
        self.assertEqual(response.status_code, 404)

    def test_non_object_payload_is_a_validation_error(self):
        response = self.client.patch(self.url, [], format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")


class CustomerCreateRuleTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.client = _client_for(self.customer)

    def test_customer_cannot_set_staff_only_fields_on_create(self):
        payloads = {
            "status": Ticket.Status.CLOSED,
            "priority": Ticket.Priority.URGENT,
            "assignee": self.agent.id,
        }
        for field, value in payloads.items():
            with self.subTest(field=field):
                response = self.client.post(
                    "/api/tickets/", {"title": "Forged", "description": "d", field: value}
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["error"]["code"], "permission_denied")
                self.assertFalse(Ticket.objects.filter(title="Forged").exists())

    def test_customer_ticket_starts_open_with_default_priority(self):
        response = self.client.post("/api/tickets/", {"title": "Plain", "description": "d"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], Ticket.Status.OPEN)
        self.assertEqual(response.data["priority"], Ticket.Priority.MEDIUM)
        self.assertIsNone(response.data["assignee"])


class StaffEditRuleTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.admin = AdminFactory()

    def test_staff_can_edit_every_field_of_any_ticket(self):
        for user in (self.agent, self.admin):
            with self.subTest(role=user.role):
                ticket = TicketFactory(customer=self.customer, status=Ticket.Status.IN_PROGRESS)
                response = _client_for(user).patch(
                    f"/api/tickets/{ticket.id}/",
                    {
                        "title": "Staff title",
                        "description": "Staff text",
                        "priority": Ticket.Priority.HIGH,
                        "assignee": self.agent.id,
                        "status": Ticket.Status.RESOLVED,
                    },
                )
                self.assertEqual(response.status_code, 200)
                ticket.refresh_from_db()
                self.assertEqual(ticket.title, "Staff title")
                self.assertEqual(ticket.description, "Staff text")
                self.assertEqual(ticket.priority, Ticket.Priority.HIGH)
                self.assertEqual(ticket.assignee, self.agent)
                self.assertEqual(ticket.status, Ticket.Status.RESOLVED)

    def test_staff_can_edit_a_closed_ticket(self):
        ticket = TicketFactory(customer=self.customer, status=Ticket.Status.CLOSED)
        response = _client_for(self.agent).patch(
            f"/api/tickets/{ticket.id}/", {"title": "Corrected title"}
        )
        self.assertEqual(response.status_code, 200)

    def test_staff_can_create_a_ticket_with_a_priority(self):
        response = _client_for(self.agent).post(
            "/api/tickets/",
            {"title": "Staff ticket", "description": "d", "priority": Ticket.Priority.HIGH},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["priority"], Ticket.Priority.HIGH)


def _serializer_class_for(user):
    view = TicketViewSet()
    view.request = SimpleNamespace(user=user)
    return view.get_serializer_class()


class TicketSerializerSelectionTests(TestCase):
    def test_customer_gets_the_restricted_serializer(self):
        self.assertIs(_serializer_class_for(UserFactory()), CustomerTicketSerializer)

    def test_agent_and_admin_get_the_full_serializer(self):
        self.assertIs(_serializer_class_for(AgentFactory()), TicketSerializer)
        self.assertIs(_serializer_class_for(AdminFactory()), TicketSerializer)

    def test_anonymous_user_gets_the_full_serializer(self):
        self.assertIs(_serializer_class_for(AnonymousUser()), TicketSerializer)

    def test_customer_serializer_ignores_staff_only_fields(self):
        agent = AgentFactory()
        serializer = CustomerTicketSerializer(
            data={
                "title": "t",
                "description": "d",
                "status": Ticket.Status.CLOSED,
                "priority": Ticket.Priority.URGENT,
                "assignee": agent.id,
            }
        )
        serializer.is_valid(raise_exception=True)
        self.assertEqual(set(serializer.validated_data), {"title", "description"})


class CustomerNameTests(TestCase):
    def setUp(self):
        self.customer = UserFactory(first_name="Sara", last_name="Ahmadi")
        self.agent = AgentFactory()
        self.ticket = TicketFactory(customer=self.customer)

    def _get(self, user, ticket=None):
        ticket = ticket or self.ticket
        return _client_for(user).get(f"/api/tickets/{ticket.id}/")

    def test_staff_see_the_full_name_of_the_customer(self):
        response = self._get(self.agent)
        self.assertEqual(response.data["customer_name"], "Sara Ahmadi")

    def test_staff_see_the_username_when_the_customer_has_no_name(self):
        nameless = UserFactory(first_name="", last_name="")
        ticket = TicketFactory(customer=nameless)
        response = self._get(self.agent, ticket)
        self.assertEqual(response.data["customer_name"], nameless.username)

    def test_a_ticket_without_a_customer_has_no_name(self):
        ticket = TicketFactory(from_visitor=True)
        response = self._get(self.agent, ticket)
        self.assertIsNone(response.data["customer_name"])

    def test_the_name_is_in_the_staff_list(self):
        response = _client_for(self.agent).get("/api/tickets/")
        row = next(item for item in response.data["results"] if item["id"] == self.ticket.id)
        self.assertEqual(row["customer_name"], "Sara Ahmadi")

    def test_customers_do_not_receive_the_name(self):
        response = self._get(self.customer)
        self.assertNotIn("customer_name", response.data)
