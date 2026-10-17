from django.contrib.admin.sites import site
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import AdminFactory, AgentFactory, TicketFactory
from tickets.models import Ticket, TicketEvent


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class TicketUpdateAuditTests(TestCase):
    def setUp(self):
        self.agent = AgentFactory()
        self.client = _client_for(self.agent)
        self.ticket = TicketFactory(priority=Ticket.Priority.LOW)
        self.url = f"/api/tickets/{self.ticket.id}/"

    def test_a_priority_change_is_recorded(self):
        response = self.client.patch(self.url, {"priority": "high"}, format="json")
        self.assertEqual(response.status_code, 200)
        event = TicketEvent.objects.get(ticket=self.ticket, field_changed="priority")
        self.assertEqual((event.old_value, event.new_value), ("low", "high"))
        self.assertEqual(event.actor, self.agent)

    def test_a_priority_change_moves_the_first_response_due_date(self):
        before = self.ticket.first_response_due_at
        self.client.patch(self.url, {"priority": "urgent"}, format="json")
        self.ticket.refresh_from_db()
        self.assertNotEqual(self.ticket.first_response_due_at, before)

    def test_a_title_edit_is_recorded(self):
        response = self.client.patch(self.url, {"title": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200)
        event = TicketEvent.objects.get(ticket=self.ticket, field_changed="title")
        self.assertEqual((event.old_value, event.new_value), (self.ticket.title, "Renamed"))

    def test_a_description_edit_is_recorded(self):
        response = self.client.patch(self.url, {"description": "A longer story"}, format="json")
        self.assertEqual(response.status_code, 200)
        event = TicketEvent.objects.get(ticket=self.ticket, field_changed="description")
        self.assertEqual(
            (event.old_value, event.new_value), ("Ticket description", "A longer story")
        )

    def test_an_unchanged_priority_records_nothing(self):
        response = self.client.patch(self.url, {"priority": "low"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TicketEvent.objects.filter(ticket=self.ticket).exists())


class TicketCreateAuditTests(TestCase):
    def setUp(self):
        self.agent = AgentFactory()
        self.client = _client_for(self.agent)

    def _create(self, **extra):
        payload = {"title": "Fresh", "description": "d", **extra}
        return self.client.post("/api/tickets/", payload, format="json")

    def test_an_assignee_given_at_creation_is_recorded(self):
        response = self._create(assignee=self.agent.id)
        self.assertEqual(response.status_code, 201)
        ticket = Ticket.objects.get(pk=response.data["id"])
        event = TicketEvent.objects.get(ticket=ticket, field_changed="assignee")
        self.assertEqual((event.old_value, event.new_value), ("", self.agent.username))
        self.assertEqual(event.actor, self.agent)

    def test_creation_without_an_assignee_records_no_assignee_event(self):
        response = self._create()
        self.assertEqual(response.status_code, 201)
        ticket = Ticket.objects.get(pk=response.data["id"])
        self.assertFalse(
            TicketEvent.objects.filter(ticket=ticket, field_changed="assignee").exists()
        )


class AdminRestoreActionAuditTests(TestCase):
    def _request(self, user):
        request = RequestFactory().post("/admin/tickets/ticket/")
        request.user = user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_restore_selected_records_one_event_per_ticket(self):
        admin_user = AdminFactory()
        tickets = [TicketFactory(), TicketFactory()]
        for ticket in tickets:
            ticket.delete()

        admin_instance = site._registry[Ticket]
        admin_instance.restore_selected(
            self._request(admin_user), Ticket.all_objects.filter(pk__in=[t.pk for t in tickets])
        )

        for ticket in tickets:
            ticket.refresh_from_db()
            self.assertFalse(ticket.is_deleted)
            event = TicketEvent.objects.get(ticket=ticket, field_changed="restored")
            self.assertEqual(event.actor, admin_user)

    def test_restore_selected_skips_live_tickets(self):
        admin_user = AdminFactory()
        live = TicketFactory()
        admin_instance = site._registry[Ticket]
        admin_instance.restore_selected(
            self._request(admin_user), Ticket.all_objects.filter(pk=live.pk)
        )
        self.assertFalse(TicketEvent.objects.filter(ticket=live).exists())
