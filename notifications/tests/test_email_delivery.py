import smtplib
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings

from accounts.models import User
from notifications.exceptions import ProviderError
from notifications.providers import deliver
from notifications.tasks import send_ticket_notification
from tickets.models import Ticket, TicketEvent


@override_settings(DEFAULT_FROM_EMAIL="support@test.local")
class EmailDeliveryTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="em_cust",
            password="pass12345",
            email="cust@example.com",
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username="em_agent",
            password="pass12345",
            email="agent@example.com",
            role=User.Role.AGENT,
        )
        self.other_agent = User.objects.create_user(
            username="em_agent2",
            password="pass12345",
            email="other@example.com",
            role=User.Role.AGENT,
        )
        self.ticket = Ticket.objects.create(
            title="Login broken", description="d", customer=self.customer, assignee=self.agent
        )

    def _event(self, field, old, new, actor):
        return TicketEvent.objects.create(
            ticket=self.ticket,
            actor=actor,
            field_changed=field,
            old_value=old,
            new_value=new,
        )

    def test_created_event_emails_the_customer_only(self):
        event = self._event("created", "", Ticket.Status.OPEN, self.customer)
        sent = deliver(event)
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["cust@example.com"])
        self.assertEqual(message.from_email, "support@test.local")
        self.assertIn(f"#{self.ticket.id}", message.subject)
        self.assertIn("Login broken", message.subject)
        self.assertIn("Current status: Open.", message.body)

    def test_status_change_notifies_customer_and_assignee(self):
        event = self._event(
            "status", Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, self.other_agent
        )
        deliver(event)
        recipients = sorted(message.to[0] for message in mail.outbox)
        self.assertEqual(recipients, ["agent@example.com", "cust@example.com"])
        for message in mail.outbox:
            self.assertEqual(len(message.to), 1)

    def test_status_change_never_emails_the_actor(self):
        event = self._event("status", Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, self.agent)
        deliver(event)
        self.assertEqual([message.to for message in mail.outbox], [["cust@example.com"]])

    def test_status_email_uses_human_readable_labels(self):
        event = self._event("status", Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, self.agent)
        deliver(event)
        message = mail.outbox[0]
        self.assertIn("from Open to In Progress", message.body)
        self.assertNotIn("in_progress", message.body)
        self.assertIn("In Progress", message.subject)

    def test_assignee_change_notifies_new_assignee_and_customer(self):
        event = self._event("assignee", "", self.other_agent.username, self.agent)
        deliver(event)
        by_recipient = {message.to[0]: message for message in mail.outbox}
        self.assertEqual(set(by_recipient), {"cust@example.com", "other@example.com"})
        self.assertIn("assigned to you", by_recipient["other@example.com"].body)
        self.assertIn(self.other_agent.username, by_recipient["cust@example.com"].body)
        self.assertNotIn("assigned to you", by_recipient["cust@example.com"].body)

    def test_unassign_email_says_unassigned(self):
        event = self._event("assignee", self.agent.username, "", self.agent)
        deliver(event)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["cust@example.com"])
        self.assertIn("unassigned", mail.outbox[0].body)

    def test_recipients_without_email_are_skipped(self):
        self.customer.email = ""
        self.customer.save()
        event = self._event("created", "", Ticket.Status.OPEN, self.customer)
        self.assertEqual(deliver(event), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_unknown_field_sends_nothing(self):
        event = self._event("priority", "low", "high", self.agent)
        self.assertEqual(deliver(event), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_special_characters_are_not_html_escaped(self):
        self.ticket.title = 'Fish & "chips"'
        self.ticket.save()
        event = self._event("created", "", Ticket.Status.OPEN, self.customer)
        deliver(event)
        message = mail.outbox[0]
        self.assertIn('Fish & "chips"', message.subject)
        self.assertIn('Fish & "chips"', message.body)
        self.assertNotIn("&amp;", message.body)
        self.assertNotIn("&quot;", message.body)

    def test_subject_is_always_a_single_line(self):
        self.ticket.title = "line one\nline two"
        self.ticket.save()
        event = self._event("created", "", Ticket.Status.OPEN, self.customer)
        deliver(event)
        self.assertNotIn("\n", mail.outbox[0].subject)
        self.assertIn("line one line two", mail.outbox[0].subject)

    def test_smtp_failures_are_raised_as_provider_error(self):
        event = self._event("created", "", Ticket.Status.OPEN, self.customer)
        for failure in (smtplib.SMTPException("boom"), ConnectionRefusedError("refused")):
            with self.subTest(failure=type(failure).__name__):
                with patch("notifications.providers.mailers") as patched_mailers:
                    patched_mailers.__getitem__.return_value.send_messages.side_effect = failure
                    with self.assertRaises(ProviderError):
                        deliver(event)

    def test_task_sends_email_once_even_when_run_twice(self):
        event = self._event("created", "", Ticket.Status.OPEN, self.customer)
        send_ticket_notification(event.id)
        send_ticket_notification(event.id)
        self.assertEqual(len(mail.outbox), 1)
