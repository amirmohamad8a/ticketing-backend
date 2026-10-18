from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import AdminFactory, AgentFactory, TagFactory, TicketFactory
from tickets.models import Ticket, TicketEvent


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _event_tuple(event):
    return (event.field_changed, event.old_value, event.new_value, event.actor_id)


class TicketAuditContractTests(TestCase):
    def setUp(self):
        self.actor = AgentFactory()
        self.first_assignee = AgentFactory()
        self.second_assignee = AgentFactory()
        self.alpha = TagFactory(name="alpha")
        self.bravo = TagFactory(name="bravo")
        self.charlie = TagFactory(name="charlie")
        self.client = _client_for(self.actor)

    def test_one_update_writes_every_ticket_event_in_order(self):
        created = self.client.post(
            "/api/tickets/",
            {
                "title": "Original title",
                "description": "Original description",
                "priority": Ticket.Priority.LOW,
                "assignee": self.first_assignee.id,
                "tags": [self.alpha.id, self.bravo.id],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        ticket = Ticket.objects.get(pk=created.data["id"])

        self.assertEqual(
            [_event_tuple(event) for event in ticket.events.order_by("id")],
            [
                ("created", "", Ticket.Status.OPEN, self.actor.id),
                ("assignee", "", self.first_assignee.username, self.actor.id),
                ("tag", "", "alpha", self.actor.id),
                ("tag", "", "bravo", self.actor.id),
            ],
        )

        updated = self.client.patch(
            f"/api/tickets/{ticket.id}/",
            {
                "status": Ticket.Status.IN_PROGRESS,
                "assignee": self.second_assignee.id,
                "priority": Ticket.Priority.HIGH,
                "title": "Renamed title",
                "description": "Renamed description",
                "tags": [self.bravo.id, self.charlie.id],
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200)

        self.assertEqual(
            [_event_tuple(event) for event in ticket.events.order_by("id")],
            [
                ("created", "", Ticket.Status.OPEN, self.actor.id),
                ("assignee", "", self.first_assignee.username, self.actor.id),
                ("tag", "", "alpha", self.actor.id),
                ("tag", "", "bravo", self.actor.id),
                ("status", Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, self.actor.id),
                (
                    "assignee",
                    self.first_assignee.username,
                    self.second_assignee.username,
                    self.actor.id,
                ),
                ("priority", Ticket.Priority.LOW, Ticket.Priority.HIGH, self.actor.id),
                ("title", "Original title", "Renamed title", self.actor.id),
                ("description", "Original description", "Renamed description", self.actor.id),
                ("tag", "alpha", "", self.actor.id),
                ("tag", "", "charlie", self.actor.id),
            ],
        )


class TagDeletionAuditContractTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)

    def test_deleting_a_tag_audits_every_ticket_that_had_it(self):
        tag = TagFactory(name="Billing")
        first = TicketFactory(tags=[tag])
        second = TicketFactory(tags=[tag])
        soft_deleted = TicketFactory(tags=[tag])
        soft_deleted.delete()
        TicketFactory()

        response = self.client.delete(f"/api/tags/{tag.id}/")
        self.assertEqual(response.status_code, 204)

        events = TicketEvent.objects.filter(field_changed="tag").order_by("ticket_id", "id")
        self.assertEqual(
            [(event.ticket_id, *_event_tuple(event)[:3]) for event in events],
            [
                (first.id, "tag", "Billing", ""),
                (second.id, "tag", "Billing", ""),
                (soft_deleted.id, "tag", "Billing", ""),
            ],
        )
        self.assertEqual({event.actor_id for event in events}, {self.admin.id})
