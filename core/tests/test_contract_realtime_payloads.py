from unittest.mock import patch

from django.db import transaction
from django.test import TestCase

from chat.offline import convert_unanswered_chat
from core.groups import AGENTS_QUEUE_GROUP, ticket_group
from core.tests.factories import AgentFactory, TicketFactory, VisitorFactory
from tickets.events import record_event
from tickets.messages import post_message
from tickets.models import Ticket


class RecordingLayer:
    def __init__(self):
        self.messages = []

    async def group_send(self, group, message):
        self.messages.append((group, message))


def _payload(event_type, event_id, ticket_id, data):
    return {"type": event_type, "id": event_id, "ticket_id": ticket_id, "data": data}


def _message(group, payload, staff_only):
    return {
        "type": "realtime.event",
        "group": group,
        "staff_only": staff_only,
        "payload": payload,
        "public_payload": payload,
    }


class RealtimePayloadContractTests(TestCase):
    def _capture(self):
        return patch("core.events.get_channel_layer")

    def _groups(self, ticket_id):
        return (ticket_group(ticket_id), AGENTS_QUEUE_GROUP)

    def test_message_created_is_published_to_both_groups_with_the_documented_data(self):
        ticket = TicketFactory()
        agent = AgentFactory()
        layer = RecordingLayer()
        with self._capture() as get_layer:
            get_layer.return_value = layer
            with self.captureOnCommitCallbacks(execute=True):
                comment, created = post_message(ticket, "Hello", author=agent)

        self.assertTrue(created)
        payload = _payload(
            "message.created",
            comment.pk,
            ticket.pk,
            {
                "message_id": comment.pk,
                "kind": "message",
                "sender_type": "agent",
                "is_internal": False,
                "client_msg_id": None,
            },
        )
        self.assertEqual(
            layer.messages,
            [(group, _message(group, payload, False)) for group in self._groups(ticket.pk)],
        )

    def test_an_internal_note_is_staff_only(self):
        ticket = TicketFactory()
        agent = AgentFactory()
        layer = RecordingLayer()
        with self._capture() as get_layer:
            get_layer.return_value = layer
            with self.captureOnCommitCallbacks(execute=True):
                comment, _created = post_message(ticket, "Secret", author=agent, is_internal=True)

        payload = layer.messages[0][1]["payload"]
        self.assertEqual(payload["id"], comment.pk)
        self.assertEqual(payload["data"]["is_internal"], True)
        self.assertEqual([message[1]["staff_only"] for message in layer.messages], [True, True])

    def test_ticket_events_carry_their_field_change_and_staff_only_flag(self):
        ticket = TicketFactory()
        agent = AgentFactory()
        layer = RecordingLayer()
        with self._capture() as get_layer:
            get_layer.return_value = layer
            with self.captureOnCommitCallbacks(execute=True):
                status_event = record_event(ticket, agent, "status", "open", "in_progress")
                assignee_event = record_event(ticket, agent, "assignee", "", agent.username)

        status_payload = _payload(
            "ticket.event",
            status_event.pk,
            ticket.pk,
            {"field_changed": "status", "old_value": "open", "new_value": "in_progress"},
        )
        assignee_payload = _payload(
            "ticket.event",
            assignee_event.pk,
            ticket.pk,
            {"field_changed": "assignee", "old_value": "", "new_value": agent.username},
        )
        expected = []
        for payload, staff_only in ((status_payload, False), (assignee_payload, True)):
            for group in self._groups(ticket.pk):
                expected.append((group, _message(group, payload, staff_only)))
        self.assertEqual(layer.messages, expected)

    def test_conversation_offline_is_published_with_contact_availability(self):
        visitor = VisitorFactory(email="visitor@example.com")
        ticket = TicketFactory(from_visitor=True, visitor=visitor)
        layer = RecordingLayer()
        with self._capture() as get_layer:
            get_layer.return_value = layer
            with self.captureOnCommitCallbacks(execute=True):
                self.assertTrue(convert_unanswered_chat(ticket.pk))

        ticket.refresh_from_db()
        self.assertEqual(ticket.channel, Ticket.Channel.OFFLINE_FORM)
        offline_messages = [
            message
            for _group, message in layer.messages
            if message["payload"]["type"] == "conversation.offline"
        ]
        self.assertEqual(len(offline_messages), 2)
        channel_event = ticket.events.get(field_changed="channel")
        expected_payload = _payload(
            "conversation.offline", channel_event.pk, ticket.pk, {"has_contact": True}
        )
        for message in offline_messages:
            self.assertEqual(message["staff_only"], False)
            self.assertEqual(message["payload"], expected_payload)

        types = [message["payload"]["type"] for _group, message in layer.messages]
        self.assertEqual(
            types,
            ["ticket.event", "ticket.event", "message.created", "message.created"]
            + ["conversation.offline", "conversation.offline"],
        )

    def test_nothing_is_sent_when_the_transaction_rolls_back(self):
        ticket = TicketFactory()
        layer = RecordingLayer()
        with self._capture() as get_layer:
            get_layer.return_value = layer
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaises(RuntimeError):
                    with transaction.atomic():
                        record_event(ticket, None, "status", "open", "in_progress")
                        raise RuntimeError("rollback")

        self.assertEqual(layer.messages, [])
        self.assertFalse(ticket.events.exists())
