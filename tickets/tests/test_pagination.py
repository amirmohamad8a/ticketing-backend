from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import AgentFactory, TicketFactory, UserFactory
from tickets.models import Ticket
from tickets.pagination import TicketCursorPagination

PAGE_SIZE = TicketCursorPagination.page_size


def _auth(client, user):
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class TicketPaginationBoundaryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.agent = AgentFactory()
        self.customer = UserFactory()
        _auth(self.client, self.agent)

    def _walk(self, url="/api/tickets/"):
        pages = []
        while url:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            pages.append([ticket["id"] for ticket in response.data["results"]])
            url = response.data["next"]
        return pages

    def test_empty_list_has_no_results_and_no_links(self):
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])
        self.assertIsNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

    def test_exactly_one_full_page_has_no_next_link(self):
        TicketFactory.create_batch(PAGE_SIZE, customer=self.customer)
        response = self.client.get("/api/tickets/")
        self.assertEqual(len(response.data["results"]), PAGE_SIZE)
        self.assertIsNone(response.data["next"])

    def test_one_more_than_a_page_spills_a_single_ticket_to_page_two(self):
        TicketFactory.create_batch(PAGE_SIZE + 1, customer=self.customer)
        pages = self._walk()
        self.assertEqual([len(page) for page in pages], [PAGE_SIZE, 1])

    def test_walking_all_pages_returns_every_ticket_once_newest_first(self):
        tickets = TicketFactory.create_batch(PAGE_SIZE * 2 + 5, customer=self.customer)
        pages = self._walk()
        self.assertEqual([len(page) for page in pages], [PAGE_SIZE, PAGE_SIZE, 5])
        flattened = [ticket_id for page in pages for ticket_id in page]
        expected = sorted((ticket.id for ticket in tickets), reverse=True)
        self.assertEqual(flattened, expected)

    def test_previous_link_returns_to_the_first_page(self):
        TicketFactory.create_batch(PAGE_SIZE + 5, customer=self.customer)
        first = self.client.get("/api/tickets/")
        self.assertIsNone(first.data["previous"])
        second = self.client.get(first.data["next"])
        self.assertIsNotNone(second.data["previous"])
        back = self.client.get(second.data["previous"])
        first_ids = [ticket["id"] for ticket in first.data["results"]]
        back_ids = [ticket["id"] for ticket in back.data["results"]]
        self.assertEqual(back_ids, first_ids)

    def test_next_link_keeps_active_filters(self):
        status = Ticket.Status.IN_PROGRESS
        TicketFactory.create_batch(PAGE_SIZE + 5, customer=self.customer)
        TicketFactory.create_batch(3, customer=self.customer, status=status)
        first = self.client.get("/api/tickets/?status=open")
        self.assertIn("status=open", first.data["next"])
        pages = self._walk("/api/tickets/?status=open")
        self.assertEqual([len(page) for page in pages], [PAGE_SIZE, 5])
        walked = {ticket_id for page in pages for ticket_id in page}
        open_tickets = Ticket.objects.filter(status=Ticket.Status.OPEN)
        self.assertEqual(walked, {ticket.id for ticket in open_tickets})

    def test_invalid_cursor_returns_not_found_envelope(self):
        response = self.client.get("/api/tickets/?cursor=not-a-valid-cursor")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "not_found")

    def test_customer_pages_only_contain_own_tickets(self):
        _auth(self.client, self.customer)
        own = TicketFactory.create_batch(PAGE_SIZE + 3, customer=self.customer)
        TicketFactory.create_batch(4)
        pages = self._walk()
        self.assertEqual([len(page) for page in pages], [PAGE_SIZE, 3])
        walked = {ticket_id for page in pages for ticket_id in page}
        self.assertEqual(walked, {ticket.id for ticket in own})
