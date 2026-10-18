from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat import presence
from chat.tokens import issue_visitor_token
from core.tests.factories import (
    AgentFactory,
    SiteFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)
from tickets.assignment import release_tickets
from tickets.models import Ticket, TicketEvent

ORIGIN = "https://example.com"
REOPENABLE = (
    Ticket.Status.WAITING_ON_CUSTOMER,
    Ticket.Status.RESOLVED,
    Ticket.Status.CLOSED,
)


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class ReopenEntryPointParityTests(TestCase):
    def setUp(self):
        self.site = SiteFactory(allowed_origins=[ORIGIN])

    def _portal_ticket(self, status):
        customer = UserFactory()
        ticket = TicketFactory(customer=customer, status=status, resolved_at=timezone.now())
        return ticket, _client_for(customer), customer

    def _visitor_ticket(self, status):
        visitor = VisitorFactory(site=self.site)
        ticket = TicketFactory(
            from_visitor=True,
            visitor=visitor,
            status=status,
            resolved_at=timezone.now(),
        )
        client = APIClient()
        client.credentials(HTTP_X_VISITOR_TOKEN=issue_visitor_token(visitor), HTTP_ORIGIN=ORIGIN)
        return ticket, client, visitor

    def _status_events(self, ticket):
        return list(
            TicketEvent.objects.filter(ticket=ticket, field_changed="status")
            .order_by("id")
            .values_list("old_value", "new_value", "actor_id")
        )

    def _portal_reply(self, status):
        ticket, client, customer = self._portal_ticket(status)
        response = client.post(
            f"/api/tickets/{ticket.id}/comments/", {"body": "Reopen please"}, format="json"
        )
        return ticket, response, customer

    def _widget_message(self, status):
        ticket, client, _visitor = self._visitor_ticket(status)
        response = client.post(
            f"/api/widget/conversations/{ticket.id}/messages/",
            {"body": "Reopen please"},
            format="json",
        )
        return ticket, response

    def _widget_attachment(self, status):
        ticket, client, _visitor = self._visitor_ticket(status)
        upload = SimpleUploadedFile("reopen.txt", b"hello", content_type="text/plain")
        response = client.post(
            f"/api/widget/conversations/{ticket.id}/attachments/",
            {"file": upload, "body": "Reopen please"},
        )
        return ticket, response

    def _open_conversation(self, status):
        ticket, client, _visitor = self._visitor_ticket(status)
        response = client.post(
            "/api/widget/conversations/", {"body": "Reopen please"}, HTTP_ORIGIN=ORIGIN
        )
        return ticket, response

    def test_all_entry_points_reopen_a_waiting_ticket_with_the_same_event(self):
        cases = [
            ("portal_comments", self._portal_reply, "customer", 201),
            ("widget_messages", self._widget_message, None, 201),
            ("widget_attachments", self._widget_attachment, None, 201),
            ("open_conversation", self._open_conversation, None, 200),
        ]
        events = []
        for name, action, actor_kind, expected_status in cases:
            with self.subTest(entry_point=name):
                ticket, response, *rest = action(Ticket.Status.WAITING_ON_CUSTOMER)
                self.assertEqual(response.status_code, expected_status)
                ticket.refresh_from_db()
                self.assertEqual(ticket.status, Ticket.Status.IN_PROGRESS)
                ticket_events = self._status_events(ticket)
                self.assertEqual(
                    ticket_events,
                    [
                        (
                            Ticket.Status.WAITING_ON_CUSTOMER,
                            Ticket.Status.IN_PROGRESS,
                            rest[0].pk if actor_kind == "customer" else None,
                        )
                    ],
                )
                events.append(ticket_events[0][:2])
        self.assertEqual(len(set(events)), 1)

    def test_finished_ticket_reopen_gaps_are_pinned(self):
        for status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
            with self.subTest(status=status, entry_point="portal_comments"):
                ticket, response, customer = self._portal_reply(status)
                self.assertEqual(response.status_code, 201)
                ticket.refresh_from_db()
                self.assertEqual(ticket.status, Ticket.Status.IN_PROGRESS)
                self.assertEqual(
                    self._status_events(ticket),
                    [(status, Ticket.Status.IN_PROGRESS, customer.pk)],
                )

            for name, action in (
                ("widget_messages", self._widget_message),
                ("widget_attachments", self._widget_attachment),
            ):
                with self.subTest(status=status, entry_point=name):
                    ticket, response = action(status)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.data["error"]["code"], "conversation_closed")
                    ticket.refresh_from_db()
                    self.assertEqual(ticket.status, status)
                    self.assertEqual(self._status_events(ticket), [])

            with self.subTest(status=status, entry_point="open_conversation"):
                ticket, response = self._open_conversation(status)
                self.assertEqual(response.status_code, 201)
                self.assertNotEqual(response.data["conversation"]["id"], ticket.id)
                ticket.refresh_from_db()
                self.assertEqual(ticket.status, status)
                self.assertEqual(self._status_events(ticket), [])


class ReleaseRoutingParityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.released_agent = AgentFactory()
        self.available_agent = AgentFactory()
        presence.heartbeat(self.available_agent.pk)

    def test_released_chat_tickets_are_rerouted_but_portal_tickets_stay_unassigned(self):
        chat = TicketFactory(
            from_visitor=True, assignee=self.released_agent, status=Ticket.Status.OPEN
        )
        portal = TicketFactory(assignee=self.released_agent, status=Ticket.Status.OPEN)
        finished = TicketFactory(
            from_visitor=True,
            assignee=self.released_agent,
            status=Ticket.Status.RESOLVED,
        )

        released = release_tickets(self.released_agent, actor=self.released_agent)

        self.assertEqual({ticket.id for ticket in released}, {chat.id, portal.id})
        chat.refresh_from_db()
        portal.refresh_from_db()
        finished.refresh_from_db()
        self.assertEqual(chat.assignee, self.available_agent)
        self.assertIsNone(portal.assignee)
        self.assertEqual(finished.assignee, self.released_agent)
