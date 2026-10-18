from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import AdminFactory, AgentFactory, TicketFactory, UserFactory
from tickets.models import Ticket, TicketEvent


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class AssigneeValidationTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.admin = AdminFactory()
        self.ticket = TicketFactory(customer=self.customer)
        self.url = f"/api/tickets/{self.ticket.id}/"
        self.client = _client_for(self.agent)

    def _assign(self, user_id):
        return self.client.patch(self.url, {"assignee": user_id}, format="json")

    def _events(self):
        return TicketEvent.objects.filter(ticket=self.ticket)

    def _assert_rejected(self, response):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("assignee", response.data["error"]["details"])
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assignee)
        self.assertFalse(self._events().exists())

    def test_assigning_the_ticket_owner_is_rejected(self):
        self._assert_rejected(self._assign(self.customer.id))

    def test_assigning_any_other_customer_is_rejected(self):
        self._assert_rejected(self._assign(UserFactory().id))

    def test_assigning_an_inactive_customer_is_rejected(self):
        self._assert_rejected(self._assign(UserFactory(is_active=False).id))

    def test_assigning_an_inactive_agent_is_rejected(self):
        self._assert_rejected(self._assign(AgentFactory(is_active=False).id))

    def test_assigning_an_inactive_admin_is_rejected(self):
        self._assert_rejected(self._assign(AdminFactory(is_active=False).id))

    def test_assigning_an_unknown_user_is_rejected(self):
        self._assert_rejected(self._assign(999999))

    def test_rejected_assignee_blocks_the_rest_of_the_payload(self):
        response = self.client.patch(
            self.url,
            {"status": Ticket.Status.IN_PROGRESS, "assignee": self.customer.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)
        self.assertFalse(self._events().exists())

    def test_active_agent_can_be_assigned_and_the_event_is_written(self):
        response = self._assign(self.agent.id)
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.agent)
        event = self._events().get()
        self.assertEqual(event.field_changed, "assignee")
        self.assertEqual(event.new_value, self.agent.username)

    def test_active_admin_can_be_assigned(self):
        response = self._assign(self.admin.id)
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.admin)

    def test_unassigning_is_always_allowed(self):
        self.ticket.assignee = self.agent
        self.ticket.save()
        response = self._assign(None)
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assignee)
        self.assertEqual(self._events().get().new_value, "")

    def test_admin_actor_is_validated_the_same_way(self):
        response = _client_for(self.admin).patch(
            self.url, {"assignee": self.customer.id}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_customer_still_cannot_send_an_assignee_at_all(self):
        response = _client_for(self.customer).patch(
            self.url, {"assignee": self.agent.id}, format="json"
        )
        self.assertEqual(response.status_code, 403)


class DeactivatedCurrentAssigneeTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.leaver = AgentFactory()
        self.agent = AgentFactory()
        self.ticket = TicketFactory(customer=self.customer, assignee=self.leaver)
        self.leaver.is_active = False
        self.leaver.save()
        self.url = f"/api/tickets/{self.ticket.id}/"
        self.client = _client_for(self.agent)

    def _events(self):
        return TicketEvent.objects.filter(ticket=self.ticket)

    def test_other_fields_can_still_be_edited_with_patch(self):
        response = self.client.patch(self.url, {"title": "Retitled"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_put_resending_the_same_assignee_is_accepted_and_writes_no_assignee_event(self):
        response = self.client.put(
            self.url,
            {"title": "Retitled", "description": "d", "assignee": self.leaver.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.leaver)
        self.assertEqual(
            set(self._events().values_list("field_changed", flat=True)),
            {"title", "description"},
        )

    def test_ticket_can_be_moved_to_an_active_agent(self):
        response = self.client.patch(self.url, {"assignee": self.agent.id}, format="json")
        self.assertEqual(response.status_code, 200)
        event = self._events().get()
        self.assertEqual(event.old_value, self.leaver.username)
        self.assertEqual(event.new_value, self.agent.username)

    def test_ticket_can_be_unassigned(self):
        response = self.client.patch(self.url, {"assignee": None}, format="json")
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assignee)

    def test_ticket_cannot_be_moved_to_another_inactive_agent(self):
        other_leaver = AgentFactory(is_active=False)
        response = self.client.patch(self.url, {"assignee": other_leaver.id}, format="json")
        self.assertEqual(response.status_code, 400)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assignee, self.leaver)
        self.assertFalse(self._events().exists())


class AssigneeOnCreateTests(TestCase):
    def setUp(self):
        self.agent = AgentFactory()
        self.client = _client_for(self.agent)

    def _create(self, assignee_id):
        return self.client.post(
            "/api/tickets/",
            {"title": "Staff ticket", "description": "d", "assignee": assignee_id},
            format="json",
        )

    def test_staff_cannot_create_a_ticket_assigned_to_a_customer(self):
        response = self._create(UserFactory().id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("assignee", response.data["error"]["details"])
        self.assertFalse(Ticket.objects.filter(title="Staff ticket").exists())
        self.assertFalse(TicketEvent.objects.exists())

    def test_staff_cannot_create_a_ticket_assigned_to_an_inactive_agent(self):
        response = self._create(AgentFactory(is_active=False).id)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Ticket.objects.filter(title="Staff ticket").exists())

    def test_staff_can_create_a_ticket_assigned_to_an_active_agent(self):
        response = self._create(self.agent.id)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["assignee"], self.agent.id)
