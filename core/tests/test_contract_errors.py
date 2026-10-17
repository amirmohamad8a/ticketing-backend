from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat.conversations import start_conversation
from core.tests.factories import AgentFactory, SiteFactory, TicketFactory, UserFactory
from tickets.models import Ticket


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class ErrorEnvelopeContractTests(TestCase):
    def assert_error(self, response, status_code, code, *, details=None):
        self.assertEqual(response.status_code, status_code)
        self.assertEqual(set(response.data), {"error"})
        body = response.data["error"]
        self.assertEqual(set(body), {"code", "message", "details"})
        self.assertEqual(body["code"], code)
        self.assertIsInstance(body["message"], str)
        self.assertTrue(body["message"])
        if details is None:
            self.assertIsNone(body["details"])
        else:
            self.assertIsNotNone(body["details"])
            for field in details:
                self.assertIn(field, body["details"])

    def test_ticket_already_assigned(self):
        owner_agent = AgentFactory()
        claiming_agent = AgentFactory()
        ticket = TicketFactory(assignee=owner_agent)

        response = _client_for(claiming_agent).post(f"/api/tickets/{ticket.id}/claim/")

        self.assert_error(response, 409, "ticket_already_assigned")

    def test_ticket_not_resolved(self):
        customer = UserFactory()
        ticket = TicketFactory(customer=customer, status=Ticket.Status.OPEN)

        response = _client_for(customer).post(
            f"/api/tickets/{ticket.id}/rating/", {"score": 5}, format="json"
        )

        self.assert_error(response, 409, "ticket_not_resolved")

    def test_ticket_already_rated(self):
        customer = UserFactory()
        ticket = TicketFactory(customer=customer, status=Ticket.Status.RESOLVED)
        client = _client_for(customer)

        first = client.post(f"/api/tickets/{ticket.id}/rating/", {"score": 5}, format="json")
        self.assertEqual(first.status_code, 201)

        response = client.post(f"/api/tickets/{ticket.id}/rating/", {"score": 4}, format="json")

        self.assert_error(response, 409, "ticket_already_rated")

    def test_conversation_closed(self):
        site = SiteFactory(allowed_origins=["https://example.com"])
        _session, ticket, _comment = start_conversation(site, "Hello")
        Ticket.objects.filter(pk=ticket.pk).update(status=Ticket.Status.RESOLVED)

        client = APIClient()
        client.credentials(
            HTTP_X_VISITOR_TOKEN=_session_token(site, ticket),
            HTTP_ORIGIN="https://example.com",
        )
        response = client.post(
            f"/api/widget/conversations/{ticket.id}/messages/",
            {"body": "Are you there?"},
            format="json",
        )

        self.assert_error(response, 409, "conversation_closed")

    def test_validation_error_for_an_illegal_status_transition(self):
        agent = AgentFactory()
        ticket = TicketFactory(status=Ticket.Status.OPEN)

        response = _client_for(agent).patch(
            f"/api/tickets/{ticket.id}/", {"status": Ticket.Status.RESOLVED}, format="json"
        )

        self.assert_error(response, 400, "validation_error", details=["status"])

    def test_validation_error_for_an_invalid_assignee(self):
        agent = AgentFactory()
        customer = UserFactory()
        ticket = TicketFactory()

        response = _client_for(agent).patch(
            f"/api/tickets/{ticket.id}/", {"assignee": customer.id}, format="json"
        )

        self.assert_error(response, 400, "validation_error", details=["assignee"])


def _session_token(site, ticket):
    from chat.tokens import issue_visitor_token

    return issue_visitor_token(ticket.visitor)
