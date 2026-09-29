from django.test import TestCase

from accounts.models import User
from notifications.tasks import send_ticket_notification
from tickets.models import Ticket, TicketEvent


class SendTicketNotificationTaskTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="sn_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="sn_agent", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)
        self.event = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=self.agent,
            field_changed="status",
            old_value=Ticket.Status.OPEN,
            new_value=Ticket.Status.IN_PROGRESS,
        )

    def test_task_logs_the_event_it_was_given(self):
        with self.assertLogs("notifications.tasks", level="INFO") as logs:
            send_ticket_notification(self.event.id)
        self.assertEqual(len(logs.output), 1)
        self.assertIn(str(self.event), logs.output[0])

    def test_task_returns_quietly_when_event_no_longer_exists(self):
        with self.assertNoLogs("notifications.tasks", level="INFO"):
            send_ticket_notification(self.event.id + 1000)
