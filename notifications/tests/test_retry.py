from unittest.mock import patch

from django.test import TestCase

from celery.utils.time import get_exponential_backoff_interval

from accounts.models import User
from notifications.exceptions import ProviderError
from notifications.models import NotificationLog
from notifications.tasks import (
    MAX_RETRIES,
    RETRY_BACKOFF_MAX_SECONDS,
    RETRY_BACKOFF_SECONDS,
    NotificationTask,
    send_ticket_notification,
)
from tickets.models import Ticket, TicketEvent

DELIVER = "notifications.tasks.deliver"


class NotificationRetryConfigTests(TestCase):
    def test_task_uses_dead_letter_base_class(self):
        self.assertIsInstance(send_ticket_notification, NotificationTask)

    def test_retry_configuration(self):
        task = send_ticket_notification
        self.assertEqual(task.autoretry_for, (ProviderError,))
        self.assertEqual(task.max_retries, MAX_RETRIES)
        self.assertEqual(task.retry_backoff, RETRY_BACKOFF_SECONDS)
        self.assertEqual(task.retry_backoff_max, RETRY_BACKOFF_MAX_SECONDS)
        self.assertTrue(task.retry_jitter)

    def test_backoff_delay_increases_between_attempts(self):
        task = send_ticket_notification
        delays = [
            get_exponential_backoff_interval(
                task.retry_backoff, attempt, task.retry_backoff_max, False
            )
            for attempt in range(task.max_retries)
        ]
        self.assertEqual(delays, [5, 10, 20, 40, 80])
        self.assertEqual(delays, sorted(set(delays)))


class NotificationRetryBehaviorTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="rt_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="rt_agent", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)
        self.event = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=self.agent,
            field_changed="status",
            old_value=Ticket.Status.OPEN,
            new_value=Ticket.Status.IN_PROGRESS,
        )

    def test_provider_failure_is_retried_until_it_succeeds(self):
        with patch(DELIVER, side_effect=[ProviderError("down"), ProviderError("down"), None]) as m:
            result = send_ticket_notification.apply(args=[self.event.id])
        self.assertTrue(result.successful())
        self.assertEqual(m.call_count, 3)
        self.assertEqual(NotificationLog.objects.filter(event=self.event).count(), 1)

    def test_provider_failure_gives_up_after_max_retries(self):
        with patch(DELIVER, side_effect=ProviderError("down")) as m:
            result = send_ticket_notification.apply(args=[self.event.id])
        self.assertTrue(result.failed())
        self.assertEqual(m.call_count, MAX_RETRIES + 1)

    def test_failed_attempts_leave_no_claim_behind(self):
        with patch(DELIVER, side_effect=ProviderError("down")):
            send_ticket_notification.apply(args=[self.event.id])
        self.assertFalse(NotificationLog.objects.exists())

    def test_final_failure_is_written_to_dead_letter_log(self):
        with patch(DELIVER, side_effect=ProviderError("down")):
            with self.assertLogs("notifications.tasks", level="ERROR") as logs:
                send_ticket_notification.apply(args=[self.event.id])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("failed permanently", logs.output[0])
        self.assertIn(str(self.event.id), logs.output[0])

    def test_successful_send_is_not_retried_and_logs_no_error(self):
        with patch(DELIVER) as m:
            with self.assertNoLogs("notifications.tasks", level="ERROR"):
                result = send_ticket_notification.apply(args=[self.event.id])
        self.assertTrue(result.successful())
        m.assert_called_once_with(self.event)

    def test_non_provider_error_is_not_retried(self):
        with patch(DELIVER, side_effect=ValueError("bug")) as m:
            result = send_ticket_notification.apply(args=[self.event.id])
        self.assertTrue(result.failed())
        self.assertEqual(m.call_count, 1)

    def test_duplicate_run_does_not_call_provider_again(self):
        with patch(DELIVER) as m:
            send_ticket_notification.apply(args=[self.event.id])
            send_ticket_notification.apply(args=[self.event.id])
        m.assert_called_once()
