from django.test import TestCase

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from tickets.models import Ticket, TicketEvent


def _auth(client, user):
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


VALID_TRANSITIONS = [
    (Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS),
    (Ticket.Status.IN_PROGRESS, Ticket.Status.WAITING_ON_CUSTOMER),
    (Ticket.Status.IN_PROGRESS, Ticket.Status.RESOLVED),
    (Ticket.Status.IN_PROGRESS, Ticket.Status.OPEN),
    (Ticket.Status.WAITING_ON_CUSTOMER, Ticket.Status.IN_PROGRESS),
    (Ticket.Status.WAITING_ON_CUSTOMER, Ticket.Status.RESOLVED),
    (Ticket.Status.RESOLVED, Ticket.Status.CLOSED),
    (Ticket.Status.RESOLVED, Ticket.Status.IN_PROGRESS),
    (Ticket.Status.CLOSED, Ticket.Status.IN_PROGRESS),
]

INVALID_TRANSITIONS = [
    (Ticket.Status.OPEN, Ticket.Status.WAITING_ON_CUSTOMER),
    (Ticket.Status.OPEN, Ticket.Status.RESOLVED),
    (Ticket.Status.OPEN, Ticket.Status.CLOSED),
    (Ticket.Status.IN_PROGRESS, Ticket.Status.CLOSED),
    (Ticket.Status.WAITING_ON_CUSTOMER, Ticket.Status.OPEN),
    (Ticket.Status.WAITING_ON_CUSTOMER, Ticket.Status.CLOSED),
    (Ticket.Status.RESOLVED, Ticket.Status.OPEN),
    (Ticket.Status.RESOLVED, Ticket.Status.WAITING_ON_CUSTOMER),
    (Ticket.Status.CLOSED, Ticket.Status.OPEN),
    (Ticket.Status.CLOSED, Ticket.Status.WAITING_ON_CUSTOMER),
    (Ticket.Status.CLOSED, Ticket.Status.RESOLVED),
]


@pytest.mark.django_db
@pytest.mark.parametrize("from_status,to_status", VALID_TRANSITIONS)
def test_valid_transition_updates_status_and_creates_event(from_status, to_status):
    agent = User.objects.create_user(
        username="tr_agent", password="pass12345", role=User.Role.AGENT
    )
    customer = User.objects.create_user(
        username="tr_cust", password="pass12345", role=User.Role.CUSTOMER
    )
    ticket = Ticket.objects.create(
        title="t", description="d", customer=customer, status=from_status
    )

    client = APIClient()
    _auth(client, agent)
    response = client.patch(f"/api/tickets/{ticket.id}/", {"status": to_status})

    assert response.status_code == 200
    ticket.refresh_from_db()
    assert ticket.status == to_status

    events = list(TicketEvent.objects.filter(ticket=ticket))
    assert len(events) == 1
    assert events[0].field_changed == "status"
    assert events[0].old_value == from_status
    assert events[0].new_value == to_status


@pytest.mark.django_db
@pytest.mark.parametrize("from_status,to_status", INVALID_TRANSITIONS)
def test_invalid_transition_returns_400_and_writes_nothing(from_status, to_status):
    agent = User.objects.create_user(
        username="itr_agent", password="pass12345", role=User.Role.AGENT
    )
    customer = User.objects.create_user(
        username="itr_cust", password="pass12345", role=User.Role.CUSTOMER
    )
    ticket = Ticket.objects.create(
        title="t", description="d", customer=customer, status=from_status
    )

    client = APIClient()
    _auth(client, agent)
    response = client.patch(f"/api/tickets/{ticket.id}/", {"status": to_status})

    assert response.status_code == 400
    ticket.refresh_from_db()
    assert ticket.status == from_status
    assert not TicketEvent.objects.filter(ticket=ticket).exists()


class TicketTransitionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            username="tt_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="tt_agent", password="pass12345", role=User.Role.AGENT
        )
        self.other_agent = User.objects.create_user(
            username="tt_agent2", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)

    def _auth(self, user):
        _auth(self.client, user)

    def test_same_status_is_noop_and_creates_no_event(self):
        self._auth(self.agent)
        response = self.client.patch(
            f"/api/tickets/{self.ticket.id}/", {"status": Ticket.Status.OPEN}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TicketEvent.objects.filter(ticket=self.ticket).exists())

    def test_assignee_change_creates_event_with_usernames(self):
        self._auth(self.agent)
        response = self.client.patch(
            f"/api/tickets/{self.ticket.id}/", {"assignee": self.other_agent.id}
        )
        self.assertEqual(response.status_code, 200)
        event = TicketEvent.objects.get(ticket=self.ticket, field_changed="assignee")
        self.assertEqual(event.old_value, "")
        self.assertEqual(event.new_value, self.other_agent.username)

    def test_reassigning_to_same_assignee_creates_no_event(self):
        self.ticket.assignee = self.agent
        self.ticket.save()
        self._auth(self.agent)
        response = self.client.patch(f"/api/tickets/{self.ticket.id}/", {"assignee": self.agent.id})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TicketEvent.objects.filter(ticket=self.ticket).exists())

    def test_status_and_assignee_change_together_creates_two_events(self):
        self._auth(self.agent)
        response = self.client.patch(
            f"/api/tickets/{self.ticket.id}/",
            {"status": Ticket.Status.IN_PROGRESS, "assignee": self.agent.id},
        )
        self.assertEqual(response.status_code, 200)
        events = TicketEvent.objects.filter(ticket=self.ticket)
        self.assertEqual(events.count(), 2)
        fields_changed = set(events.values_list("field_changed", flat=True))
        self.assertEqual(fields_changed, {"status", "assignee"})

    def test_event_actor_is_requesting_user(self):
        self._auth(self.agent)
        self.client.patch(f"/api/tickets/{self.ticket.id}/", {"status": Ticket.Status.IN_PROGRESS})
        event = TicketEvent.objects.get(ticket=self.ticket)
        self.assertEqual(event.actor, self.agent)

    def test_chained_transitions_full_lifecycle(self):
        self._auth(self.agent)
        for status in [
            Ticket.Status.IN_PROGRESS,
            Ticket.Status.WAITING_ON_CUSTOMER,
            Ticket.Status.RESOLVED,
            Ticket.Status.CLOSED,
        ]:
            response = self.client.patch(f"/api/tickets/{self.ticket.id}/", {"status": status})
            self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.CLOSED)
        self.assertEqual(TicketEvent.objects.filter(ticket=self.ticket).count(), 4)


class TicketEventsEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            username="ev_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        self.other_customer = User.objects.create_user(
            username="ev_cust2", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="ev_agent", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)

    def _auth(self, user):
        _auth(self.client, user)

    def test_unauthenticated_request_rejected(self):
        response = self.client.get(f"/api/tickets/{self.ticket.id}/events/")
        self.assertEqual(response.status_code, 401)

    def test_owner_can_view_own_ticket_events(self):
        self._auth(self.agent)
        self.client.patch(f"/api/tickets/{self.ticket.id}/", {"status": Ticket.Status.IN_PROGRESS})
        self._auth(self.customer)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/events/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["field_changed"], "status")

    def test_other_customer_cannot_view_events(self):
        self._auth(self.other_customer)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/events/")
        self.assertEqual(response.status_code, 404)

    def test_agent_can_view_any_ticket_events(self):
        self._auth(self.agent)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/events/")
        self.assertEqual(response.status_code, 200)

    def test_events_returned_in_chronological_order(self):
        self._auth(self.agent)
        self.client.patch(f"/api/tickets/{self.ticket.id}/", {"status": Ticket.Status.IN_PROGRESS})
        self.client.patch(
            f"/api/tickets/{self.ticket.id}/", {"status": Ticket.Status.WAITING_ON_CUSTOMER}
        )
        response = self.client.get(f"/api/tickets/{self.ticket.id}/events/")
        self.assertEqual(response.status_code, 200)
        values = [row["new_value"] for row in response.data]
        self.assertEqual(values, [Ticket.Status.IN_PROGRESS, Ticket.Status.WAITING_ON_CUSTOMER])
