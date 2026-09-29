from django.core import mail
from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from config.celery import app
from notifications.models import NotificationLog
from notifications.tasks import send_ticket_notification
from tickets.models import Ticket, TicketEvent


@override_settings(DEFAULT_FROM_EMAIL="support@test.local")
class NotificationFlowTests(TestCase):
    def setUp(self):
        previous = app.conf.task_always_eager
        app.conf.task_always_eager = True
        self.addCleanup(setattr, app.conf, "task_always_eager", previous)

        self.client = APIClient()
        self.customer = User.objects.create_user(
            username="fl_cust",
            password="pass12345",
            email="cust@example.com",
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username="fl_agent",
            password="pass12345",
            email="agent@example.com",
            role=User.Role.AGENT,
        )
        self.other_agent = User.objects.create_user(
            username="fl_agent2",
            password="pass12345",
            email="other@example.com",
            role=User.Role.AGENT,
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)

    def _auth(self, user):
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def _send(self, method, url, payload):
        with self.captureOnCommitCallbacks(execute=True):
            return getattr(self.client, method)(url, payload)

    def _recipients(self):
        return sorted(message.to[0] for message in mail.outbox)

    def test_ticket_creation_sends_one_confirmation_to_the_customer(self):
        self._auth(self.customer)
        response = self._send(
            "post", "/api/tickets/", {"title": "Printer on fire", "description": "details"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["cust@example.com"])
        self.assertIn("Printer on fire", mail.outbox[0].subject)
        self.assertEqual(NotificationLog.objects.count(), 1)

    def test_status_change_emails_customer_and_assignee(self):
        self.ticket.assignee = self.other_agent
        self.ticket.save()
        self._auth(self.agent)
        response = self._send(
            "patch", f"/api/tickets/{self.ticket.id}/", {"status": Ticket.Status.IN_PROGRESS}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._recipients(), ["cust@example.com", "other@example.com"])
        self.assertEqual(NotificationLog.objects.count(), 1)

    def test_assignment_emails_customer_and_new_assignee(self):
        self._auth(self.agent)
        response = self._send(
            "patch", f"/api/tickets/{self.ticket.id}/", {"assignee": self.other_agent.id}
        )
        self.assertEqual(response.status_code, 200)
        by_recipient = {message.to[0]: message for message in mail.outbox}
        self.assertEqual(set(by_recipient), {"cust@example.com", "other@example.com"})
        self.assertIn("assigned to you", by_recipient["other@example.com"].body)

    def test_update_without_audited_change_sends_nothing(self):
        self._auth(self.agent)
        response = self._send("patch", f"/api/tickets/{self.ticket.id}/", {"title": "Renamed"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(NotificationLog.objects.exists())

    def test_invalid_transition_sends_nothing(self):
        self._auth(self.agent)
        response = self._send(
            "patch", f"/api/tickets/{self.ticket.id}/", {"status": Ticket.Status.CLOSED}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(NotificationLog.objects.exists())

    def test_replaying_the_same_event_does_not_send_again(self):
        self._auth(self.customer)
        self._send("post", "/api/tickets/", {"title": "Once only", "description": "details"})
        self.assertEqual(len(mail.outbox), 1)
        event = TicketEvent.objects.get(field_changed="created", new_value=Ticket.Status.OPEN)
        send_ticket_notification.delay(event.id)
        send_ticket_notification.delay(event.id)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(NotificationLog.objects.count(), 1)
