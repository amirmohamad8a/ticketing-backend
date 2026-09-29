from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import User
from notifications.models import NotificationLog
from notifications.tasks import build_idempotency_key, send_ticket_notification
from tickets.models import Ticket, TicketEvent


class NotificationIdempotencyTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="id_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="id_agent", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)
        self.event = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=self.agent,
            field_changed="status",
            old_value=Ticket.Status.OPEN,
            new_value=Ticket.Status.IN_PROGRESS,
        )

    def test_key_is_derived_from_event_id(self):
        self.assertEqual(build_idempotency_key(self.event.id), f"ticket-event-{self.event.id}")

    def test_first_run_claims_key_and_sends(self):
        with self.assertLogs("notifications.tasks", level="INFO") as logs:
            send_ticket_notification(self.event.id)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Sending notification", logs.output[0])
        log = NotificationLog.objects.get()
        self.assertEqual(log.idempotency_key, build_idempotency_key(self.event.id))
        self.assertEqual(log.event, self.event)

    def test_rerun_for_same_event_does_not_send_again(self):
        send_ticket_notification(self.event.id)
        with self.assertLogs("notifications.tasks", level="INFO") as logs:
            send_ticket_notification(self.event.id)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Skipping duplicate notification", logs.output[0])
        self.assertNotIn("Sending notification", logs.output[0])
        self.assertEqual(NotificationLog.objects.count(), 1)

    def test_different_events_are_each_sent_once(self):
        other_event = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=self.agent,
            field_changed="assignee",
            old_value="",
            new_value=self.agent.username,
        )
        send_ticket_notification(self.event.id)
        send_ticket_notification(other_event.id)
        self.assertEqual(NotificationLog.objects.count(), 2)

    def test_failed_send_releases_claim_so_retry_can_send(self):
        with patch("notifications.tasks.logger") as mocked_logger:
            mocked_logger.info.side_effect = RuntimeError("provider down")
            with self.assertRaises(RuntimeError):
                send_ticket_notification(self.event.id)
        self.assertFalse(NotificationLog.objects.exists())

        with self.assertLogs("notifications.tasks", level="INFO") as logs:
            send_ticket_notification(self.event.id)
        self.assertIn("Sending notification", logs.output[0])
        self.assertEqual(NotificationLog.objects.count(), 1)

    def test_missing_event_creates_no_claim(self):
        send_ticket_notification(self.event.id + 1000)
        self.assertFalse(NotificationLog.objects.exists())

    def test_database_rejects_duplicate_key(self):
        NotificationLog.objects.create(
            idempotency_key=build_idempotency_key(self.event.id), event=self.event
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                NotificationLog.objects.create(
                    idempotency_key=build_idempotency_key(self.event.id), event=self.event
                )
