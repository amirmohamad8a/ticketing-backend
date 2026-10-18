from dataclasses import FrozenInstanceError
from types import SimpleNamespace

from django.test import TestCase

from accounts.models import User
from core.tests.factories import AgentFactory, UserFactory, VisitorFactory
from tickets.models import SenderType
from tickets.participants import Participant, ParticipantKind


class ParticipantTests(TestCase):
    def test_staff_participant(self):
        user = AgentFactory()
        participant = Participant(user=user)
        self.assertEqual(participant.kind, ParticipantKind.STAFF)
        self.assertTrue(participant.is_staff)
        self.assertFalse(participant.is_customer)
        self.assertFalse(participant.is_visitor)
        self.assertTrue(participant.sees_internal_notes)
        self.assertEqual(participant.sender_type, SenderType.AGENT)
        self.assertEqual(participant.socket_identity, f"user:{user.pk}")
        self.assertEqual(participant.reader_filter, {"user": user})
        self.assertEqual(participant.read_filter, {"user": user})
        self.assertEqual(participant.ownership_filter, {})
        self.assertEqual(participant.owner_filter, {})
        self.assertEqual(participant.actor, user)

    def test_customer_participant(self):
        user = UserFactory(role=User.Role.CUSTOMER)
        participant = Participant(user=user)
        self.assertEqual(participant.kind, ParticipantKind.CUSTOMER)
        self.assertFalse(participant.is_staff)
        self.assertTrue(participant.is_customer)
        self.assertFalse(participant.is_visitor)
        self.assertFalse(participant.sees_internal_notes)
        self.assertEqual(participant.sender_type, SenderType.CUSTOMER)
        self.assertEqual(participant.socket_identity, f"user:{user.pk}")
        self.assertEqual(participant.reader_filter, {"user": user})
        self.assertEqual(participant.ownership_filter, {"customer": user})
        self.assertEqual(participant.actor, user)

    def test_visitor_participant(self):
        visitor = VisitorFactory(name="Sara")
        participant = Participant(visitor=visitor)
        self.assertEqual(participant.kind, ParticipantKind.VISITOR)
        self.assertFalse(participant.is_staff)
        self.assertFalse(participant.is_customer)
        self.assertTrue(participant.is_visitor)
        self.assertFalse(participant.sees_internal_notes)
        self.assertEqual(participant.sender_type, SenderType.VISITOR)
        self.assertEqual(participant.socket_identity, f"visitor:{visitor.pk}")
        self.assertEqual(participant.reader_filter, {"visitor": visitor})
        self.assertEqual(participant.ownership_filter, {"visitor": visitor})
        self.assertEqual(participant.display_name, "Sara")
        self.assertIsNone(participant.actor)

    def test_staff_display_name_is_the_full_name_or_support(self):
        user = AgentFactory(first_name="Sara", last_name="Ahmadi")
        self.assertEqual(Participant(user=user).display_name, "Sara Ahmadi")
        user.first_name = ""
        user.last_name = ""
        self.assertEqual(Participant(user=user).display_name, "Support")

    def test_from_request_uses_an_authenticated_user(self):
        user = UserFactory()
        request = SimpleNamespace(user=user, auth=None)
        self.assertEqual(Participant.from_request(request).user, user)

    def test_from_request_uses_a_visitor_auth(self):
        visitor = VisitorFactory()
        request = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=False),
            auth=visitor,
        )
        self.assertEqual(Participant.from_request(request).visitor, visitor)

    def test_a_participant_needs_exactly_one_owner(self):
        user = UserFactory()
        visitor = VisitorFactory()
        with self.assertRaises(ValueError):
            Participant()
        with self.assertRaises(ValueError):
            Participant(user=user, visitor=visitor)
        with self.assertRaises(ValueError):
            Participant.from_request(SimpleNamespace(user=None, auth=None))

    def test_a_participant_is_immutable(self):
        participant = Participant(user=UserFactory())
        with self.assertRaises(FrozenInstanceError):
            participant.user = None
