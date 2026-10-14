import shutil
import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.db.models import Q
from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from chat.conversations import start_conversation
from chat.models import Site, Visitor
from core.demo import (
    AGENT_USERNAME,
    CANNED_SHORTCUTS,
    CHAT_TICKETS,
    CUSTOMER_USERNAME,
    DEMO_PASSWORD,
    DEMO_USERNAMES,
    PORTAL_TICKETS,
    SITE_KEY,
    TAG_NAMES,
    _discard_files,
    reset_demo_data,
    seed_demo_data,
)
from core.tests.factories import AttachmentFactory, CommentFactory, TicketFactory, UserFactory
from tickets.models import CannedReply, Comment, Tag, Ticket, TicketEvent, TicketRating

TEST_MEDIA_ROOT = tempfile.mkdtemp()
TOTAL = len(PORTAL_TICKETS) + len(CHAT_TICKETS)


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _demo_snapshot():
    tickets = Ticket.all_objects.filter(
        Q(customer__username__in=DEMO_USERNAMES) | Q(site__key=SITE_KEY)
    )
    return {
        "tickets": sorted(tickets.values_list("title", "channel", "status", "priority")),
        "comments": sorted(
            Comment.objects.filter(ticket__in=tickets).values_list("body", "is_internal", "kind")
        ),
        "events": sorted(
            TicketEvent.objects.filter(ticket__in=tickets).values_list(
                "field_changed", "old_value", "new_value"
            )
        ),
        "ratings": sorted(
            TicketRating.objects.filter(ticket__in=tickets).values_list("score", "comment")
        ),
        "visitors": sorted(
            Visitor.objects.filter(site__key=SITE_KEY).values_list("name", "phone", "email")
        ),
        "tags": sorted(Tag.objects.filter(name__in=TAG_NAMES).values_list("name", "color")),
        "canned": sorted(
            CannedReply.objects.filter(shortcut__in=CANNED_SHORTCUTS).values_list(
                "shortcut", "title", "body"
            )
        ),
        "users": sorted(
            User.objects.filter(username__in=DEMO_USERNAMES).values_list(
                "username", "role", "first_name", "last_name", "is_active", "max_concurrent_chats"
            )
        ),
    }


class ResetDemoTests(TestCase):
    def _make_a_mess(self):
        customer = User.objects.get(username=CUSTOMER_USERNAME)
        agent = User.objects.get(username=AGENT_USERNAME)
        created = _client_for(customer).post(
            "/api/tickets/", {"title": "Demo leftover", "description": "d"}, format="json"
        )
        self.assertEqual(created.status_code, 201)
        start_conversation(Site.objects.get(key=SITE_KEY), "A visitor from the recording")
        invoice = Ticket.objects.get(title=PORTAL_TICKETS[1]["title"])
        Ticket.objects.filter(pk=invoice.pk).update(status=Ticket.Status.CLOSED)
        Ticket.objects.get(title=PORTAL_TICKETS[0]["title"]).delete()
        CommentFactory(ticket=invoice, author=agent, body="leftover comment")
        agent.role = User.Role.ADMIN
        agent.is_active = False
        agent.first_name = "Changed"
        agent.phone = "09123456789"
        agent.max_concurrent_chats = 9
        agent.set_password("changed-pass-1")
        agent.save()
        User.objects.filter(pk=agent.pk).update(last_chat_assigned_at=agent.date_joined)

    def test_reset_on_an_empty_database_seeds_everything(self):
        created = reset_demo_data()
        self.assertEqual(created, TOTAL)
        self.assertEqual(Ticket.objects.count(), TOTAL)

    def test_reset_removes_what_was_created_through_the_demo(self):
        seed_demo_data()
        baseline = _demo_snapshot()
        self._make_a_mess()
        self.assertNotEqual(_demo_snapshot(), baseline)

        created = reset_demo_data()

        self.assertEqual(created, TOTAL)
        self.assertEqual(_demo_snapshot(), baseline)
        self.assertFalse(Ticket.all_objects.filter(title="Demo leftover").exists())
        self.assertFalse(Comment.objects.filter(body="leftover comment").exists())
        self.assertEqual(Visitor.objects.filter(site__key=SITE_KEY).count(), len(CHAT_TICKETS))

    def test_reset_restores_the_demo_users(self):
        seed_demo_data()
        self._make_a_mess()
        reset_demo_data()
        agent = User.objects.get(username=AGENT_USERNAME)
        self.assertEqual(agent.role, User.Role.AGENT)
        self.assertTrue(agent.is_active)
        self.assertIsNone(agent.phone)
        self.assertEqual(agent.max_concurrent_chats, User.DEFAULT_MAX_CONCURRENT_CHATS)
        self.assertIsNone(agent.last_chat_assigned_at)
        self.assertTrue(agent.check_password(DEMO_PASSWORD))
        self.assertNotEqual(agent.first_name, "Changed")

    def test_reset_restores_the_status_of_demo_tickets(self):
        seed_demo_data()
        self._make_a_mess()
        reset_demo_data()
        invoice = Ticket.objects.get(title=PORTAL_TICKETS[1]["title"])
        self.assertEqual(invoice.status, Ticket.Status.OPEN)
        self.assertTrue(Ticket.objects.filter(title=PORTAL_TICKETS[0]["title"]).exists())

    def test_reset_leaves_everything_outside_the_demo_alone(self):
        seed_demo_data()
        other = UserFactory()
        shared_tag = Tag.objects.get(name="billing")
        ticket = TicketFactory(customer=other, tags=[shared_tag])
        comment = CommentFactory(ticket=ticket, author=other)
        reset_demo_data()
        self.assertTrue(User.objects.filter(pk=other.pk).exists())
        self.assertTrue(Ticket.objects.filter(pk=ticket.pk).exists())
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())
        self.assertEqual(Tag.objects.filter(name__iexact="billing").count(), 1)
        self.assertIn(shared_tag.pk, ticket.tags.values_list("pk", flat=True))

    def test_reset_is_repeatable(self):
        seed_demo_data()
        reset_demo_data()
        first = _demo_snapshot()
        reset_demo_data()
        self.assertEqual(_demo_snapshot(), first)

    def test_the_commands_report_what_they_did(self):
        out = StringIO()
        call_command("reset_demo", stdout=out)
        self.assertIn(f"{TOTAL} ticket(s) seeded from scratch", out.getvalue())


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ResetDemoFilesTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_files_of_removed_data_are_deleted_once_the_transaction_commits(self):
        seed_demo_data()
        ticket = Ticket.objects.get(title=PORTAL_TICKETS[0]["title"])
        comment = CommentFactory(ticket=ticket, author=ticket.customer)
        ticket_file = AttachmentFactory(ticket=ticket, uploaded_by=ticket.customer)
        comment_file = AttachmentFactory(
            on_comment=True, comment=comment, uploaded_by=ticket.customer
        )
        agent = User.objects.get(username=AGENT_USERNAME)
        agent.avatar.save("avatar.png", ContentFile(b"png"), save=True)
        names = [ticket_file.file.name, comment_file.file.name, agent.avatar.name]
        for name in names:
            self.assertTrue(default_storage.exists(name))

        with self.captureOnCommitCallbacks(execute=True):
            reset_demo_data()

        for name in names:
            self.assertFalse(default_storage.exists(name))
        agent.refresh_from_db()
        self.assertFalse(agent.avatar)


class DiscardFilesTests(TestCase):
    def test_a_file_that_cannot_be_deleted_is_logged_and_skipped(self):
        with patch("core.demo.default_storage") as storage:
            storage.delete.side_effect = [OSError("locked"), None]
            with self.assertLogs("core.demo", level="WARNING"):
                _discard_files(["a.png", "b.png"])
        self.assertEqual(storage.delete.call_count, 2)

    def test_blank_and_repeated_names_are_ignored(self):
        with patch("core.demo.default_storage") as storage:
            _discard_files(["a.png", "", None, "a.png"])
        storage.delete.assert_called_once_with("a.png")
