from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from tickets.models import Ticket


class TicketQuerysetScopingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer1 = User.objects.create_user(
            username="scopecust1", password="pass12345", role=User.Role.CUSTOMER
        )
        self.customer2 = User.objects.create_user(
            username="scopecust2", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="scopeagent1", password="pass12345", role=User.Role.AGENT
        )
        self.ticket1 = Ticket.objects.create(
            title="Ticket one", description="d", customer=self.customer1
        )
        self.ticket2 = Ticket.objects.create(
            title="Ticket two", description="d", customer=self.customer2
        )

    def _auth(self, user):
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_unauthenticated_list_rejected(self):
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, 401)

    def test_customer_list_only_shows_own_tickets(self):
        self._auth(self.customer1)
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, 200)
        ids = [t["id"] for t in response.data]
        self.assertEqual(ids, [self.ticket1.id])

    def test_agent_list_shows_all_tickets(self):
        self._auth(self.agent)
        response = self.client.get("/api/tickets/")
        ids = {t["id"] for t in response.data}
        self.assertEqual(ids, {self.ticket1.id, self.ticket2.id})

    def test_customer_can_retrieve_own_ticket(self):
        self._auth(self.customer1)
        response = self.client.get(f"/api/tickets/{self.ticket1.id}/")
        self.assertEqual(response.status_code, 200)

    def test_customer_cannot_retrieve_other_customers_ticket(self):
        self._auth(self.customer1)
        response = self.client.get(f"/api/tickets/{self.ticket2.id}/")
        self.assertEqual(response.status_code, 404)

    def test_agent_can_retrieve_any_ticket(self):
        self._auth(self.agent)
        response = self.client.get(f"/api/tickets/{self.ticket1.id}/")
        self.assertEqual(response.status_code, 200)

    def test_customer_create_ticket_assigns_self_as_customer(self):
        self._auth(self.customer1)
        response = self.client.post(
            "/api/tickets/", {"title": "New ticket", "description": "details"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["customer"], self.customer1.id)

    def test_customer_cannot_override_customer_field_on_create(self):
        self._auth(self.customer1)
        response = self.client.post(
            "/api/tickets/",
            {"title": "New ticket", "description": "details", "customer": self.customer2.id},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["customer"], self.customer1.id)
