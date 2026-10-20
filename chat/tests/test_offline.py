from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from chat import presence
from chat.assignment import route_queued_chats
from chat.offline import (
    EarlyCandidateConfirmation,
    convert_due_chats,
    convert_unanswered_chat,
    due_chat_ticket_ids,
)
from core.tests.factories import AgentFactory, SiteFactory, TicketFactory, VisitorFactory
from tickets.events import TicketEventField, record_event
from tickets.models import Comment, Ticket

CONVERSATIONS_URL = "/api/widget/conversations/"
ORIGIN = "https://example.com"


class OfflineSchedulingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.site = SiteFactory(
            allowed_origins=[ORIGIN],
            offline_timeout_minutes=5,
        )

    def _start(self):
        with patch("chat.conversations.convert_to_offline") as task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    CONVERSATIONS_URL,
                    {"site_key": self.site.key, "body": "Hello"},
                    HTTP_ORIGIN=ORIGIN,
                )
        self.assertEqual(response.status_code, 201)
        return Ticket.objects.get(pk=response.data["conversation"]["id"]), task

    def test_no_online_agents_schedule_an_immediate_conversion(self):
        ticket, task = self._start()
        task.apply_async.assert_called_once_with(args=[ticket.pk], countdown=0)

    def test_an_online_agent_delays_the_conversion_by_the_site_timeout(self):
        agent = AgentFactory()
        presence.set_status(agent.pk, presence.STATUS_AWAY)
        ticket, task = self._start()
        task.apply_async.assert_called_once_with(args=[ticket.pk], countdown=300)

    def test_a_routed_chat_does_not_schedule_an_offline_conversion(self):
        agent = AgentFactory()
        presence.heartbeat(agent.pk)
        ticket, task = self._start()
        self.assertEqual(ticket.assignee, agent)
        task.apply_async.assert_not_called()


class QueuedChatDrainTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.agent = AgentFactory(max_concurrent_chats=1)
        presence.heartbeat(self.agent.pk)
        self.busy = TicketFactory(
            from_visitor=True,
            assignee=self.agent,
            status=Ticket.Status.IN_PROGRESS,
        )
        self.queued = TicketFactory(from_visitor=True)

    def test_a_full_agent_does_not_take_a_queued_chat(self):
        self.assertEqual(route_queued_chats(), 0)
        self.queued.refresh_from_db()
        self.assertIsNone(self.queued.assignee)

    def test_capacity_freed_later_assigns_the_queued_chat_in_the_sweep(self):
        Ticket.objects.filter(pk=self.busy.pk).update(status=Ticket.Status.RESOLVED)
        self.assertEqual(route_queued_chats(), 1)
        self.queued.refresh_from_db()
        self.assertEqual(self.queued.assignee, self.agent)


class EarlyCandidateConfirmationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_a_first_sighting_is_not_confirmed(self):
        confirmation = EarlyCandidateConfirmation(key="early-test", ttl_seconds=10)
        self.assertEqual(confirmation.confirm({1, 2}), set())

    def test_a_second_sighting_confirms_the_shared_candidates(self):
        confirmation = EarlyCandidateConfirmation(key="early-test", ttl_seconds=10)
        self.assertEqual(confirmation.confirm({1, 2}), set())
        self.assertEqual(confirmation.confirm({1, 2, 3}), {1, 2})

    def test_the_configured_ttl_is_written_with_the_candidates(self):
        confirmation = EarlyCandidateConfirmation(key="early-test", ttl_seconds=42)
        with patch("chat.offline.cache.set") as set_cache:
            confirmation.confirm({1, 2})
        args, kwargs = set_cache.call_args
        self.assertEqual(args[0], "early-test")
        self.assertEqual(set(args[1]), {1, 2})
        self.assertEqual(kwargs["timeout"], 42)


class OfflineSweepTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.agent = AgentFactory(max_concurrent_chats=1)
        presence.set_status(self.agent.pk, presence.STATUS_AWAY)
        self.ticket = TicketFactory(
            from_visitor=True,
            status=Ticket.Status.OPEN,
        )

    def test_an_online_but_away_agent_keeps_the_chat_until_the_timeout(self):
        self.assertEqual(convert_due_chats(), 0)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.channel, Ticket.Channel.CHAT)

    def test_the_sweep_converts_the_chat_after_the_site_timeout(self):
        later = timezone.now() + timedelta(minutes=6)
        self.assertEqual(convert_due_chats(now=later), 1)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.channel, Ticket.Channel.OFFLINE_FORM)


class AssignmentWindowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.now = timezone.now()
        self.site = SiteFactory(offline_timeout_minutes=5)
        self.agent = AgentFactory()
        presence.set_status(self.agent.pk, presence.STATUS_AWAY)
        self.ticket = TicketFactory(
            from_visitor=True,
            visitor=VisitorFactory(site=self.site),
            status=Ticket.Status.OPEN,
        )
        Ticket.objects.filter(pk=self.ticket.pk).update(created_at=self.now - timedelta(minutes=20))

    def _assign(self, at):
        with patch("django.utils.timezone.now", return_value=at):
            record_event(
                ticket=self.ticket,
                actor=None,
                field_changed=TicketEventField.ASSIGNEE,
                old_value="",
                new_value=self.agent.username,
            )
        Ticket.objects.filter(pk=self.ticket.pk).update(assignee=self.agent)

    def test_a_chat_assigned_late_waits_the_timeout_from_the_assignment(self):
        self._assign(self.now - timedelta(seconds=30))
        self.assertEqual(due_chat_ticket_ids(now=self.now + timedelta(minutes=4)), [])
        self.assertEqual(due_chat_ticket_ids(now=self.now + timedelta(minutes=5)), [self.ticket.pk])

    def test_a_scheduled_conversion_skips_an_online_assignee_within_the_timeout(self):
        self._assign(self.now - timedelta(minutes=1))
        self.assertFalse(convert_unanswered_chat(self.ticket.pk))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.channel, Ticket.Channel.CHAT)

    def test_a_scheduled_conversion_converts_once_the_assignment_timeout_has_passed(self):
        self._assign(self.now - timedelta(minutes=6))
        self.assertTrue(convert_unanswered_chat(self.ticket.pk))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.channel, Ticket.Channel.OFFLINE_FORM)

    def test_the_offline_notice_asks_for_contact_details_without_blaming_availability(self):
        self._assign(self.now - timedelta(minutes=6))
        convert_unanswered_chat(self.ticket.pk)
        notice = Comment.objects.get(ticket=self.ticket, kind=Comment.Kind.SYSTEM)
        self.assertEqual(
            notice.body,
            "We could not reach an agent in time. Leave your contact details and we will get "
            "back to you.",
        )
