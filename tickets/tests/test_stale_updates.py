from django.test import TestCase

from accounts.models import User
from core.errors import DomainValidationError
from core.tests.factories import AgentFactory, TicketFactory
from tickets.models import Ticket, TicketEvent
from tickets.services import update_ticket


class UpdateTicketStaleInstanceTests(TestCase):
    def setUp(self):
        self.agent = AgentFactory()
        self.ticket = TicketFactory(title="Original", status=Ticket.Status.OPEN)

    def test_the_status_transition_is_validated_against_the_stored_status(self):
        stale = Ticket.objects.get(pk=self.ticket.pk)
        Ticket.objects.filter(pk=self.ticket.pk).update(status=Ticket.Status.IN_PROGRESS)

        result = update_ticket(stale, self.agent, {"status": Ticket.Status.WAITING_ON_CUSTOMER})

        self.assertEqual(result.status, Ticket.Status.WAITING_ON_CUSTOMER)
        event = TicketEvent.objects.get(ticket=self.ticket, field_changed="status")
        self.assertEqual((event.old_value, event.new_value), ("in_progress", "waiting_on_customer"))

    def test_an_impossible_transition_from_the_stored_status_is_rejected(self):
        stale = Ticket.objects.get(pk=self.ticket.pk)
        Ticket.objects.filter(pk=self.ticket.pk).update(status=Ticket.Status.CLOSED)

        with self.assertRaises(DomainValidationError):
            update_ticket(stale, self.agent, {"status": Ticket.Status.OPEN})

        self.assertEqual(Ticket.objects.get(pk=self.ticket.pk).status, Ticket.Status.CLOSED)
        self.assertFalse(TicketEvent.objects.filter(ticket=self.ticket).exists())

    def test_a_stale_field_is_audited_against_the_stored_value(self):
        stale = Ticket.objects.get(pk=self.ticket.pk)
        Ticket.objects.filter(pk=self.ticket.pk).update(title="Renamed")

        update_ticket(stale, self.agent, {"title": "Original"})

        self.assertEqual(Ticket.objects.get(pk=self.ticket.pk).title, "Original")
        event = TicketEvent.objects.get(ticket=self.ticket, field_changed="title")
        self.assertEqual((event.old_value, event.new_value), ("Renamed", "Original"))

    def test_the_returned_instance_reflects_the_stored_row(self):
        stale = Ticket.objects.get(pk=self.ticket.pk)
        assignee = User.objects.create_user(
            username="stale_other", password="pass12345", role=User.Role.AGENT
        )
        Ticket.objects.filter(pk=self.ticket.pk).update(title="Renamed")

        result = update_ticket(stale, self.agent, {"assignee": assignee})

        self.assertIs(result, stale)
        self.assertEqual(result.title, "Renamed")
        self.assertEqual(result.assignee, assignee)
