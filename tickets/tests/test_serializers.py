from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import AgentFactory, TicketFactory, UserFactory
from tickets.models import TicketEvent
from tickets.serializers import TicketSerializer


def _auth(client, user):
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class TicketSerializerActorTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.data = {"title": "t", "description": "d"}

    def _create(self, context):
        serializer = TicketSerializer(data=self.data, context=context)
        serializer.is_valid(raise_exception=True)
        return serializer.save(customer=self.customer)

    def test_create_without_request_records_event_without_actor(self):
        ticket = self._create({})
        event = TicketEvent.objects.get(ticket=ticket)
        self.assertIsNone(event.actor)
        self.assertEqual(event.field_changed, "created")

    def test_create_with_anonymous_request_records_event_without_actor(self):
        request = SimpleNamespace(user=AnonymousUser())
        ticket = self._create({"request": request})
        self.assertIsNone(TicketEvent.objects.get(ticket=ticket).actor)

    def test_create_with_authenticated_request_records_that_actor(self):
        request = SimpleNamespace(user=self.customer)
        ticket = self._create({"request": request})
        self.assertEqual(TicketEvent.objects.get(ticket=ticket).actor, self.customer)


class TicketUnassignTests(TestCase):
    def test_unassigning_records_an_event_with_empty_new_value(self):
        agent = AgentFactory()
        ticket = TicketFactory(assignee=agent)
        client = APIClient()
        _auth(client, agent)
        response = client.patch(f"/api/tickets/{ticket.id}/", {"assignee": None}, format="json")
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.assignee)
        event = TicketEvent.objects.get(ticket=ticket, field_changed="assignee")
        self.assertEqual(event.old_value, agent.username)
        self.assertEqual(event.new_value, "")
