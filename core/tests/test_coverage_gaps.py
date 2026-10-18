import asyncio
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from chat.offline import convert_due_chats, convert_unanswered_chat, due_chat_ticket_ids
from core.events import close_user_sockets, publish, publish_typing
from core.groups import ticket_group, user_group
from core.tests.factories import (
    AgentFactory,
    CommentFactory,
    SiteFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)
from tickets.messages import post_message
from tickets.models import Comment, Ticket
from tickets.participants import Participant


class RecordingLayer:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    async def group_send(self, group, message):
        if self.fail:
            raise RuntimeError("channel layer down")
        self.messages.append((group, message))


class RealtimeEventsCoverageTests(TestCase):
    def _capture(self, layer):
        return patch("core.events.get_channel_layer", return_value=layer)

    def test_delivery_is_skipped_when_there_is_no_channel_layer(self):
        with patch("core.events.get_channel_layer", return_value=None):
            with self.captureOnCommitCallbacks(execute=True):
                publish("ticket.event", 1, 1, {"field_changed": "status"})

    def test_group_send_errors_are_logged_and_do_not_escape(self):
        layer = RecordingLayer(fail=True)
        with self._capture(layer):
            with self.assertLogs("core.events", level="ERROR") as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    publish("ticket.event", 1, 1, {"field_changed": "status"})
        self.assertEqual(len(logs.records), 2)

    def test_close_user_sockets_delivers_the_close_message(self):
        layer = RecordingLayer()
        with self._capture(layer):
            with self.captureOnCommitCallbacks(execute=True):
                close_user_sockets(42)
        self.assertEqual(layer.messages, [(user_group(42), {"type": "realtime.close"})])

    def test_close_errors_are_logged(self):
        with self._capture(RecordingLayer(fail=True)):
            with self.assertLogs("core.events", level="ERROR"):
                with self.captureOnCommitCallbacks(execute=True):
                    close_user_sockets(42)

    def test_publish_typing_sends_to_the_ticket_group(self):
        layer = RecordingLayer()
        with self._capture(layer):
            asyncio.run(publish_typing(9, True, "user:1", "agent", "Sara"))
        group, message = layer.messages[0]
        self.assertEqual(group, ticket_group(9))
        self.assertEqual(
            message,
            {
                "type": "realtime.typing",
                "sender": "user:1",
                "payload": {
                    "type": "typing",
                    "ticket_id": 9,
                    "is_typing": True,
                    "sender_type": "agent",
                    "sender_name": "Sara",
                },
            },
        )

    def test_publish_typing_errors_are_logged(self):
        with self._capture(RecordingLayer(fail=True)):
            with self.assertLogs("core.events", level="ERROR"):
                asyncio.run(publish_typing(9, False, "user:1", "agent", "Sara"))


class OfflineCoverageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_an_assigned_chat_with_an_offline_assignee_is_an_early_candidate(self):
        agent = AgentFactory()
        site = SiteFactory(offline_timeout_minutes=5)
        visitor = VisitorFactory(site=site)
        ticket = TicketFactory(
            from_visitor=True,
            visitor=visitor,
            assignee=agent,
            status=Ticket.Status.OPEN,
        )
        now = timezone.now()
        self.assertEqual(due_chat_ticket_ids(now=now + timedelta(minutes=1)), [])
        self.assertEqual(due_chat_ticket_ids(now=now + timedelta(minutes=2)), [ticket.pk])

    def test_unknown_non_chat_finished_and_answered_tickets_are_not_converted(self):
        self.assertFalse(convert_unanswered_chat(999999))

        portal = TicketFactory()
        self.assertFalse(convert_unanswered_chat(portal.pk))

        finished = TicketFactory(from_visitor=True, status=Ticket.Status.RESOLVED)
        self.assertFalse(convert_unanswered_chat(finished.pk))

        answered = TicketFactory(from_visitor=True, status=Ticket.Status.OPEN)
        agent = AgentFactory()
        CommentFactory(ticket=answered, author=agent)
        self.assertFalse(convert_unanswered_chat(answered.pk))

    def test_one_failed_conversion_is_logged_and_the_sweep_continues(self):
        with patch("chat.offline.due_chat_ticket_ids", return_value=[1]):
            with patch("chat.offline.convert_unanswered_chat", side_effect=RuntimeError("boom")):
                with patch("chat.offline.route_queued_chats", return_value=0):
                    with self.assertLogs("chat.offline", level="ERROR") as logs:
                        self.assertEqual(convert_due_chats(), 0)
        self.assertEqual(len(logs.records), 1)


class MessageServiceCoverageTests(TestCase):
    def setUp(self):
        self.ticket = TicketFactory()
        self.agent = AgentFactory()
        self.customer = UserFactory()
        self.visitor = VisitorFactory()

    def test_visitor_messages_are_never_internal(self):
        comment, _created = post_message(
            self.ticket, "hello", Participant(visitor=self.visitor), is_internal=True
        )
        self.assertFalse(comment.is_internal)

    def test_system_messages_need_no_sender(self):
        comment, created = post_message(self.ticket, "notice", kind=Comment.Kind.SYSTEM)
        self.assertTrue(created)
        self.assertEqual(comment.kind, Comment.Kind.SYSTEM)
        self.assertIsNone(comment.author_id)
        self.assertIsNone(comment.visitor_id)

    def test_a_message_needs_exactly_one_sender(self):
        with self.assertRaises(ValueError):
            post_message(self.ticket, "nobody")
        with self.assertRaises(ValueError):
            Participant(self.agent, self.visitor)

    def test_integrity_error_for_a_client_id_used_by_another_sender_is_a_validation_error(self):
        CommentFactory(
            ticket=self.ticket,
            author=self.agent,
            client_msg_id="shared-id",
        )
        with patch("tickets.messages.Comment.objects.create", side_effect=IntegrityError):
            with self.assertRaises(ValidationError):
                post_message(
                    self.ticket,
                    "hello",
                    Participant(self.customer),
                    client_msg_id="shared-id",
                )

    def test_an_integrity_error_without_a_client_id_is_reraised(self):
        with patch("tickets.messages.Comment.objects.create", side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                post_message(self.ticket, "hello", Participant(self.agent))
