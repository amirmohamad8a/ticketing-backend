from unittest.mock import patch

from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from tickets.models import Ticket, TicketEvent

TASK = "tickets.events.send_ticket_notification"


def _auth(client, user):
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class NotificationTriggerTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            username="nt_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="nt_agent", password="pass12345", role=User.Role.AGENT
        )
        self.other_agent = User.objects.create_user(
            username="nt_agent2", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)

    def _auth(self, user):
        _auth(self.client, user)

    def _patch_ticket(self, payload):
        with patch(TASK) as task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(f"/api/tickets/{self.ticket.id}/", payload)
        return response, task

    def test_ticket_creation_enqueues_one_task_for_created_event(self):
        self._auth(self.customer)
        with patch(TASK) as task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    "/api/tickets/", {"title": "New ticket", "description": "details"}
                )
        self.assertEqual(response.status_code, 201)
        event = TicketEvent.objects.get(ticket_id=response.data["id"])
        self.assertEqual(event.field_changed, "created")
        self.assertEqual(event.old_value, "")
        self.assertEqual(event.new_value, Ticket.Status.OPEN)
        self.assertEqual(event.actor, self.customer)
        task.delay.assert_called_once_with(event.id)

    def test_status_change_enqueues_one_task(self):
        self._auth(self.agent)
        response, task = self._patch_ticket({"status": Ticket.Status.IN_PROGRESS})
        self.assertEqual(response.status_code, 200)
        event = TicketEvent.objects.get(ticket=self.ticket, field_changed="status")
        task.delay.assert_called_once_with(event.id)

    def test_assignee_change_enqueues_one_task(self):
        self._auth(self.agent)
        response, task = self._patch_ticket({"assignee": self.other_agent.id})
        self.assertEqual(response.status_code, 200)
        event = TicketEvent.objects.get(ticket=self.ticket, field_changed="assignee")
        task.delay.assert_called_once_with(event.id)

    def test_status_and_assignee_change_enqueue_one_task_each(self):
        self._auth(self.agent)
        response, task = self._patch_ticket(
            {"status": Ticket.Status.IN_PROGRESS, "assignee": self.agent.id}
        )
        self.assertEqual(response.status_code, 200)
        event_ids = set(TicketEvent.objects.filter(ticket=self.ticket).values_list("id", flat=True))
        self.assertEqual(len(event_ids), 2)
        self.assertEqual(task.delay.call_count, 2)
        enqueued = {call.args[0] for call in task.delay.call_args_list}
        self.assertEqual(enqueued, event_ids)

    def test_update_without_audited_change_enqueues_nothing(self):
        self._auth(self.agent)
        response, task = self._patch_ticket({"status": Ticket.Status.OPEN, "title": "Renamed"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TicketEvent.objects.filter(ticket=self.ticket).exists())
        task.delay.assert_not_called()

    def test_invalid_transition_enqueues_nothing(self):
        self._auth(self.agent)
        response, task = self._patch_ticket({"status": Ticket.Status.CLOSED})
        self.assertEqual(response.status_code, 400)
        task.delay.assert_not_called()

    def test_task_is_deferred_until_commit(self):
        self._auth(self.agent)
        with patch(TASK) as task:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.client.patch(
                    f"/api/tickets/{self.ticket.id}/", {"status": Ticket.Status.IN_PROGRESS}
                )
            task.delay.assert_not_called()
        self.assertEqual(len(callbacks), 1)
