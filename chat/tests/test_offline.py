from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from chat import presence
from chat.assignment import route_queued_chats
from chat.offline import convert_due_chats
from core.tests.factories import AgentFactory, SiteFactory, TicketFactory
from tickets.models import Ticket

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
