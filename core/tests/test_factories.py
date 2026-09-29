import shutil
import tempfile

from django.test import TestCase, override_settings

from accounts.models import User
from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    AttachmentFactory,
    CommentFactory,
    NotificationLogFactory,
    TicketEventFactory,
    TicketFactory,
    UserFactory,
)
from notifications.tasks import build_idempotency_key
from tickets.models import Ticket

TEST_MEDIA_ROOT = tempfile.mkdtemp()


class UserFactoryTests(TestCase):
    def test_default_user_is_customer_with_email_and_usable_password(self):
        user = UserFactory()
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertTrue(user.email)
        self.assertTrue(user.check_password("pass12345"))

    def test_users_get_unique_usernames(self):
        users = UserFactory.create_batch(3)
        self.assertEqual(len({user.username for user in users}), 3)

    def test_role_factories_set_the_role(self):
        self.assertEqual(AgentFactory().role, User.Role.AGENT)
        self.assertEqual(AdminFactory().role, User.Role.ADMIN)

    def test_password_can_be_overridden(self):
        user = UserFactory(password="another-pass1")
        self.assertTrue(user.check_password("another-pass1"))


class TicketFactoryTests(TestCase):
    def test_defaults(self):
        ticket = TicketFactory()
        self.assertEqual(ticket.status, Ticket.Status.OPEN)
        self.assertEqual(ticket.priority, Ticket.Priority.MEDIUM)
        self.assertIsNone(ticket.assignee)
        self.assertEqual(ticket.customer.role, User.Role.CUSTOMER)

    def test_overrides(self):
        agent = AgentFactory()
        ticket = TicketFactory(
            assignee=agent,
            status=Ticket.Status.RESOLVED,
            priority=Ticket.Priority.URGENT,
        )
        self.assertEqual(ticket.assignee, agent)
        self.assertEqual(ticket.status, Ticket.Status.RESOLVED)
        self.assertEqual(ticket.priority, Ticket.Priority.URGENT)

    def test_event_factory_builds_a_status_change_by_an_agent(self):
        event = TicketEventFactory()
        self.assertEqual(event.field_changed, "status")
        self.assertEqual(event.old_value, Ticket.Status.OPEN)
        self.assertEqual(event.new_value, Ticket.Status.IN_PROGRESS)
        self.assertEqual(event.actor.role, User.Role.AGENT)

    def test_comment_factory_defaults_to_a_public_comment(self):
        comment = CommentFactory()
        self.assertFalse(comment.is_internal)
        self.assertTrue(comment.body)
        self.assertIsNotNone(comment.ticket)


class NotificationLogFactoryTests(TestCase):
    def test_key_is_derived_from_the_event(self):
        log = NotificationLogFactory()
        self.assertEqual(log.idempotency_key, build_idempotency_key(log.event.id))


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AttachmentFactoryTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_defaults_attach_to_a_ticket(self):
        attachment = AttachmentFactory()
        self.assertIsNotNone(attachment.ticket)
        self.assertIsNone(attachment.comment)
        self.assertEqual(attachment.size, len(b"hello world"))
        self.assertEqual(attachment.content_type, "text/plain")
        attachment.clean()

    def test_on_comment_trait_attaches_to_a_comment(self):
        attachment = AttachmentFactory(on_comment=True)
        self.assertIsNone(attachment.ticket)
        self.assertIsNotNone(attachment.comment)
        attachment.clean()
