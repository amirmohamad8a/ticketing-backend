from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from tickets.models import Ticket
from tickets.validators import MAX_BODY_LENGTH


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
        ids = [t["id"] for t in response.data["results"]]
        self.assertEqual(ids, [self.ticket1.id])

    def test_agent_list_shows_all_tickets(self):
        self._auth(self.agent)
        response = self.client.get("/api/tickets/")
        ids = {t["id"] for t in response.data["results"]}
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

    def test_oversized_description_is_rejected(self):
        self._auth(self.customer1)
        response = self.client.post(
            "/api/tickets/",
            {"title": "New ticket", "description": "x" * (MAX_BODY_LENGTH + 1)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("description", response.data["error"]["details"])

    def test_oversized_description_is_rejected_on_update(self):
        self._auth(self.customer1)
        response = self.client.patch(
            f"/api/tickets/{self.ticket1.id}/",
            {"description": "x" * (MAX_BODY_LENGTH + 1)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("description", response.data["error"]["details"])


class TicketListPaginationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.agent = User.objects.create_user(
            username="pg_agent", password="pass12345", role=User.Role.AGENT
        )
        self.customer = User.objects.create_user(
            username="pg_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        refresh = RefreshToken.for_user(self.agent)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_list_response_has_pagination_keys(self):
        Ticket.objects.create(title="t", description="d", customer=self.customer)
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, 200)
        for key in ("results", "next", "previous"):
            self.assertIn(key, response.data)

    def test_list_is_capped_at_page_size_with_next_link(self):
        for i in range(25):
            Ticket.objects.create(title=f"t{i}", description="d", customer=self.customer)
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertIsNotNone(response.data["next"])

    def test_next_link_returns_remaining_tickets(self):
        for i in range(25):
            Ticket.objects.create(title=f"t{i}", description="d", customer=self.customer)
        first_page = self.client.get("/api/tickets/")
        second_page = self.client.get(first_page.data["next"])
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data["results"]), 5)
        self.assertIsNone(second_page.data["next"])
