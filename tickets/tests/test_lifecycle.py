from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import AgentFactory, TicketFactory, UserFactory
from tickets import lifecycle
from tickets.lifecycle import close_due_tickets, reopen_on_customer_reply
from tickets.models import Ticket
from tickets.tasks import auto_close_resolved

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _resolved(days, **kwargs):
    return TicketFactory(
        status=Ticket.Status.RESOLVED, resolved_at=NOW - timedelta(days=days), **kwargs
    )


@override_settings(AUTO_CLOSE_AFTER_DAYS=7)
class CloseDueTicketsTests(TestCase):
    def _status(self, ticket):
        return Ticket.all_objects.values_list("status", flat=True).get(pk=ticket.pk)

    def test_an_old_resolved_ticket_is_closed_through_the_state_machine(self):
        ticket = _resolved(8)
        self.assertEqual(close_due_tickets(now=NOW), 1)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CLOSED)
        self.assertEqual(ticket.resolved_at, NOW - timedelta(days=8))
        event = ticket.events.get()
        self.assertEqual(
            (event.field_changed, event.old_value, event.new_value),
            ("status", "resolved", "closed"),
        )
        self.assertIsNone(event.actor)

    def test_a_recently_resolved_ticket_is_left_alone(self):
        ticket = TicketFactory(
            status=Ticket.Status.RESOLVED,
            resolved_at=NOW - timedelta(days=6, hours=23),
        )
        self.assertEqual(close_due_tickets(now=NOW), 0)
        self.assertEqual(self._status(ticket), Ticket.Status.RESOLVED)
        self.assertFalse(ticket.events.exists())

    def test_the_exact_cutoff_is_included(self):
        ticket = _resolved(7)
        self.assertEqual(close_due_tickets(now=NOW), 1)
        self.assertEqual(self._status(ticket), Ticket.Status.CLOSED)

    def test_only_resolved_tickets_are_closed(self):
        old = NOW - timedelta(days=30)
        untouched = [
            TicketFactory(status=Ticket.Status.OPEN, resolved_at=old),
            TicketFactory(status=Ticket.Status.IN_PROGRESS, resolved_at=old),
            TicketFactory(status=Ticket.Status.WAITING_ON_CUSTOMER, resolved_at=old),
            TicketFactory(status=Ticket.Status.CLOSED, resolved_at=old),
        ]
        self.assertEqual(close_due_tickets(now=NOW), 0)
        for ticket in untouched:
            with self.subTest(status=ticket.status):
                self.assertEqual(self._status(ticket), ticket.status)
                self.assertFalse(ticket.events.exists())

    def test_a_resolved_ticket_without_a_resolution_time_is_left_alone(self):
        ticket = TicketFactory(status=Ticket.Status.RESOLVED)
        self.assertEqual(close_due_tickets(now=NOW), 0)
        self.assertEqual(self._status(ticket), Ticket.Status.RESOLVED)

    def test_deleted_tickets_are_left_alone(self):
        ticket = _resolved(30)
        ticket.delete()
        self.assertEqual(close_due_tickets(now=NOW), 0)
        self.assertEqual(self._status(ticket), Ticket.Status.RESOLVED)

    def test_visitor_conversations_are_closed_too(self):
        ticket = _resolved(10, from_visitor=True)
        self.assertEqual(close_due_tickets(now=NOW), 1)
        self.assertEqual(self._status(ticket), Ticket.Status.CLOSED)

    def test_running_again_does_nothing_more(self):
        ticket = _resolved(10)
        self.assertEqual(close_due_tickets(now=NOW), 1)
        self.assertEqual(close_due_tickets(now=NOW), 0)
        self.assertEqual(ticket.events.count(), 1)

    def test_every_due_ticket_is_closed_in_one_run(self):
        tickets = [_resolved(days) for days in (8, 9, 40)]
        self.assertEqual(close_due_tickets(now=NOW), 3)
        for ticket in tickets:
            self.assertEqual(self._status(ticket), Ticket.Status.CLOSED)

    def test_the_period_comes_from_the_setting(self):
        ticket = _resolved(2)
        self.assertEqual(close_due_tickets(now=NOW), 0)
        with override_settings(AUTO_CLOSE_AFTER_DAYS=1):
            self.assertEqual(close_due_tickets(now=NOW), 1)
        self.assertEqual(self._status(ticket), Ticket.Status.CLOSED)

    def test_the_default_clock_is_the_current_time(self):
        ticket = TicketFactory(
            status=Ticket.Status.RESOLVED,
            resolved_at=datetime.now(UTC) - timedelta(days=8),
        )
        self.assertEqual(close_due_tickets(), 1)
        self.assertEqual(self._status(ticket), Ticket.Status.CLOSED)

    def test_one_failing_ticket_does_not_stop_the_others(self):
        broken = _resolved(10)
        healthy = _resolved(11)
        original = lifecycle.change_status

        def flaky(ticket, new_status, request=None):
            if ticket.pk == broken.pk:
                raise RuntimeError("boom")
            return original(ticket, new_status, request)

        with patch("tickets.lifecycle.change_status", flaky):
            with self.assertLogs("tickets.lifecycle", level="ERROR") as logs:
                closed = close_due_tickets(now=NOW)

        self.assertEqual(closed, 1)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(self._status(broken), Ticket.Status.RESOLVED)
        self.assertEqual(self._status(healthy), Ticket.Status.CLOSED)


@override_settings(AUTO_CLOSE_AFTER_DAYS=7)
class AutoCloseTaskTests(TestCase):
    def test_the_task_closes_due_tickets_and_is_idempotent(self):
        ticket = TicketFactory(
            status=Ticket.Status.RESOLVED,
            resolved_at=datetime.now(UTC) - timedelta(days=9),
        )
        self.assertEqual(auto_close_resolved(), 1)
        self.assertEqual(auto_close_resolved(), 0)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.CLOSED)
        self.assertEqual(ticket.events.count(), 1)

    def test_the_task_is_named_and_scheduled(self):
        self.assertEqual(auto_close_resolved.name, "tickets.auto_close_resolved")
        entry = settings.CELERY_BEAT_SCHEDULE["tickets-auto-close-resolved"]
        self.assertEqual(entry["task"], auto_close_resolved.name)
        self.assertEqual(entry["schedule"], timedelta(hours=1))


class ReopenServiceTests(TestCase):
    def test_a_resolved_ticket_is_reopened_and_its_resolution_cleared(self):
        ticket = _resolved(1)
        self.assertTrue(reopen_on_customer_reply(ticket.pk))
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.IN_PROGRESS)
        self.assertIsNone(ticket.resolved_at)
        event = ticket.events.get()
        self.assertEqual(
            (event.field_changed, event.old_value, event.new_value),
            ("status", "resolved", "in_progress"),
        )
        self.assertIsNone(event.actor)

    def test_the_actor_is_taken_from_the_request(self):
        customer = UserFactory()
        ticket = _resolved(1, customer=customer)
        reopen_on_customer_reply(ticket.pk, SimpleNamespace(user=customer))
        self.assertEqual(ticket.events.get().actor, customer)

    def test_a_closed_ticket_is_reopened(self):
        ticket = TicketFactory(status=Ticket.Status.CLOSED, resolved_at=NOW)
        self.assertTrue(reopen_on_customer_reply(ticket.pk))
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.IN_PROGRESS)

    def test_unfinished_tickets_are_left_alone(self):
        for status in (
            Ticket.Status.OPEN,
            Ticket.Status.IN_PROGRESS,
            Ticket.Status.WAITING_ON_CUSTOMER,
        ):
            with self.subTest(status=status):
                ticket = TicketFactory(status=status)
                self.assertFalse(reopen_on_customer_reply(ticket.pk))
                ticket.refresh_from_db()
                self.assertEqual(ticket.status, status)
                self.assertFalse(ticket.events.exists())

    def test_unknown_and_deleted_tickets_are_ignored(self):
        self.assertFalse(reopen_on_customer_reply(999999))
        ticket = _resolved(1)
        ticket.delete()
        self.assertFalse(reopen_on_customer_reply(ticket.pk))


class ReopenOnReplyApiTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.owner = _client_for(self.customer)
        self.staff = _client_for(self.agent)

    def _reply(self, client, ticket, **extra):
        payload = {"body": "It is still broken", **extra}
        return client.post(f"/api/tickets/{ticket.id}/comments/", payload, format="json")

    def _stored(self, ticket):
        return Ticket.objects.get(pk=ticket.pk)

    def test_a_customer_reply_reopens_a_resolved_ticket(self):
        ticket = _resolved(1, customer=self.customer)
        response = self._reply(self.owner, ticket)
        self.assertEqual(response.status_code, 201)
        stored = self._stored(ticket)
        self.assertEqual(stored.status, Ticket.Status.IN_PROGRESS)
        self.assertIsNone(stored.resolved_at)
        event = ticket.events.get()
        self.assertEqual((event.old_value, event.new_value), ("resolved", "in_progress"))
        self.assertEqual(event.actor, self.customer)

    def test_a_customer_reply_reopens_a_closed_ticket(self):
        ticket = TicketFactory(customer=self.customer, status=Ticket.Status.CLOSED, resolved_at=NOW)
        self.assertEqual(self._reply(self.owner, ticket).status_code, 201)
        self.assertEqual(self._stored(ticket).status, Ticket.Status.IN_PROGRESS)

    def test_the_reply_is_stored_with_the_reopening(self):
        ticket = _resolved(1, customer=self.customer)
        response = self._reply(self.owner, ticket)
        self.assertEqual(ticket.comments.get().pk, response.data["id"])

    def test_active_tickets_keep_their_status(self):
        for status in (
            Ticket.Status.OPEN,
            Ticket.Status.IN_PROGRESS,
            Ticket.Status.WAITING_ON_CUSTOMER,
        ):
            with self.subTest(status=status):
                ticket = TicketFactory(customer=self.customer, status=status)
                self.assertEqual(self._reply(self.owner, ticket).status_code, 201)
                self.assertEqual(self._stored(ticket).status, status)
                self.assertFalse(ticket.events.exists())

    def test_a_staff_reply_does_not_reopen(self):
        ticket = _resolved(1, customer=self.customer)
        self.assertEqual(self._reply(self.staff, ticket).status_code, 201)
        self.assertEqual(self._stored(ticket).status, Ticket.Status.RESOLVED)

    def test_another_customer_cannot_reopen_the_ticket(self):
        ticket = _resolved(1, customer=self.customer)
        response = self._reply(_client_for(UserFactory()), ticket)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._stored(ticket).status, Ticket.Status.RESOLVED)

    def test_the_internal_flag_does_not_stop_a_customer_reopening(self):
        ticket = _resolved(1, customer=self.customer)
        self._reply(self.owner, ticket, is_internal=True)
        self.assertEqual(self._stored(ticket).status, Ticket.Status.IN_PROGRESS)

    def test_a_retried_reply_does_not_reopen_the_ticket_again(self):
        ticket = _resolved(1, customer=self.customer)
        first = self._reply(self.owner, ticket, client_msg_id="retry-1")
        self.assertEqual(first.status_code, 201)
        lifecycle.change_status(self._stored(ticket), Ticket.Status.RESOLVED)
        again = self._reply(self.owner, ticket, client_msg_id="retry-1")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(self._stored(ticket).status, Ticket.Status.RESOLVED)
