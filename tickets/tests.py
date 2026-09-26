from django.contrib.admin.sites import site
from django.db.models import ProtectedError
from django.test import TestCase

from accounts.models import User
from tickets.models import Ticket


class TicketModelTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="cust1", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="agent1", password="pass12345", role=User.Role.AGENT
        )

    def test_create_ticket_minimal(self):
        ticket = Ticket.objects.create(
            title="Cannot log in", description="I get an error on login.", customer=self.customer
        )
        self.assertEqual(ticket.status, Ticket.Status.OPEN)
        self.assertEqual(ticket.priority, Ticket.Priority.MEDIUM)
        self.assertIsNone(ticket.assignee)

    def test_create_ticket_with_assignee_and_priority(self):
        ticket = Ticket.objects.create(
            title="Server down",
            description="500 errors across the board.",
            customer=self.customer,
            assignee=self.agent,
            priority=Ticket.Priority.URGENT,
            status=Ticket.Status.IN_PROGRESS,
        )
        self.assertEqual(ticket.assignee, self.agent)
        self.assertEqual(ticket.priority, Ticket.Priority.URGENT)
        self.assertEqual(ticket.status, Ticket.Status.IN_PROGRESS)

    def test_timestamps_set_on_create(self):
        ticket = Ticket.objects.create(
            title="Billing question", description="Why was I charged twice?", customer=self.customer
        )
        self.assertIsNotNone(ticket.created_at)
        self.assertIsNotNone(ticket.updated_at)

    def test_updated_at_changes_on_save(self):
        ticket = Ticket.objects.create(
            title="Feature request", description="Add dark mode.", customer=self.customer
        )
        original_updated_at = ticket.updated_at
        ticket.status = Ticket.Status.IN_PROGRESS
        ticket.save()
        ticket.refresh_from_db()
        self.assertGreater(ticket.updated_at, original_updated_at)

    def test_deleting_assignee_sets_null(self):
        ticket = Ticket.objects.create(
            title="Password reset",
            description="Need help resetting password.",
            customer=self.customer,
            assignee=self.agent,
        )
        self.agent.delete()
        ticket.refresh_from_db()
        self.assertIsNone(ticket.assignee)

    def test_deleting_customer_with_tickets_is_protected(self):
        Ticket.objects.create(
            title="Refund request", description="Please refund my order.", customer=self.customer
        )
        with self.assertRaises(ProtectedError):
            self.customer.delete()

    def test_str_representation(self):
        ticket = Ticket.objects.create(
            title="Login issue", description="Details here.", customer=self.customer
        )
        self.assertEqual(str(ticket), f"#{ticket.pk} Login issue")

    def test_default_ordering_is_newest_first(self):
        first = Ticket.objects.create(title="First", description="d", customer=self.customer)
        second = Ticket.objects.create(title="Second", description="d", customer=self.customer)
        tickets = list(Ticket.objects.all())
        self.assertEqual(tickets, [second, first])


class TicketAdminRegistrationTests(TestCase):
    def test_ticket_model_registered_in_admin(self):
        self.assertIn(Ticket, site._registry)

    def test_admin_list_display_includes_key_fields(self):
        admin_instance = site._registry[Ticket]
        for field in ("status", "priority", "customer", "assignee"):
            self.assertIn(field, admin_instance.list_display)
