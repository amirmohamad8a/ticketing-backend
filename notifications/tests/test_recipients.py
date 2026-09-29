from django.test import TestCase

from accounts.models import User
from notifications.emails import get_recipients
from tickets.models import Ticket, TicketEvent


class RecipientRuleTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="rc_cust",
            password="pass12345",
            email="cust@example.com",
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username="rc_agent",
            password="pass12345",
            email="agent@example.com",
            role=User.Role.AGENT,
        )
        self.other_agent = User.objects.create_user(
            username="rc_agent2",
            password="pass12345",
            email="other@example.com",
            role=User.Role.AGENT,
        )
        self.ticket = Ticket.objects.create(
            title="t", description="d", customer=self.customer, assignee=self.agent
        )

    def _event(self, field, old, new, actor):
        return TicketEvent.objects.create(
            ticket=self.ticket,
            actor=actor,
            field_changed=field,
            old_value=old,
            new_value=new,
        )

    def _emails(self, event):
        return sorted(user.email for user in get_recipients(event))

    def test_status_change_by_customer_notifies_assignee_only(self):
        event = self._event("status", Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, self.customer)
        self.assertEqual(self._emails(event), ["agent@example.com"])

    def test_status_change_on_unassigned_ticket_notifies_customer_only(self):
        self.ticket.assignee = None
        self.ticket.save()
        event = self._event(
            "status", Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, self.other_agent
        )
        self.assertEqual(self._emails(event), ["cust@example.com"])

    def test_shared_email_address_is_notified_once(self):
        self.agent.email = "cust@example.com"
        self.agent.save()
        event = self._event(
            "status", Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, self.other_agent
        )
        self.assertEqual(self._emails(event), ["cust@example.com"])

    def test_unknown_new_assignee_username_is_ignored(self):
        event = self._event("assignee", "", "ghost", self.agent)
        self.assertEqual(self._emails(event), ["cust@example.com"])

    def test_customer_without_email_does_not_block_assignee_notification(self):
        self.customer.email = ""
        self.customer.save()
        event = self._event(
            "status", Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, self.other_agent
        )
        self.assertEqual(self._emails(event), ["agent@example.com"])

    def test_event_without_actor_notifies_everyone_involved(self):
        event = self._event("status", Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, None)
        self.assertEqual(self._emails(event), ["agent@example.com", "cust@example.com"])
