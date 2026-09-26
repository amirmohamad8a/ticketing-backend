import shutil
import tempfile

from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from tickets.models import Attachment, Comment, Ticket, TicketEvent


class TicketModelTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="cust1", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="agent1", password="pass12345", role=User.Role.AGENT
        )

    def test_create_ticket_minimal(self):
        ticket = Ticket.objects.create(
            title="Cannot log in", description="I get an error on login.", customer=self.customer
        )
        self.assertEqual(ticket.status, Ticket.Status.OPEN)
        self.assertEqual(ticket.priority, Ticket.Priority.MEDIUM)
        self.assertIsNone(ticket.assignee)

    def test_create_ticket_with_assignee_and_priority(self):
        ticket = Ticket.objects.create(
            title="Server down",
            description="500 errors across the board.",
            customer=self.customer,
            assignee=self.agent,
            priority=Ticket.Priority.URGENT,
            status=Ticket.Status.IN_PROGRESS,
        )
        self.assertEqual(ticket.assignee, self.agent)
        self.assertEqual(ticket.priority, Ticket.Priority.URGENT)
        self.assertEqual(ticket.status, Ticket.Status.IN_PROGRESS)

    def test_timestamps_set_on_create(self):
        ticket = Ticket.objects.create(
            title="Billing question", description="Why was I charged twice?", customer=self.customer
        )
        self.assertIsNotNone(ticket.created_at)
        self.assertIsNotNone(ticket.updated_at)

    def test_updated_at_changes_on_save(self):
        ticket = Ticket.objects.create(
            title="Feature request", description="Add dark mode.", customer=self.customer
        )
        original_updated_at = ticket.updated_at
        ticket.status = Ticket.Status.IN_PROGRESS
        ticket.save()
        ticket.refresh_from_db()
        self.assertGreater(ticket.updated_at, original_updated_at)

    def test_deleting_assignee_sets_null(self):
        ticket = Ticket.objects.create(
            title="Password reset",
            description="Need help resetting password.",
            customer=self.customer,
            assignee=self.agent,
        )
        self.agent.delete()
        ticket.refresh_from_db()
        self.assertIsNone(ticket.assignee)

    def test_deleting_customer_with_tickets_is_protected(self):
        Ticket.objects.create(
            title="Refund request", description="Please refund my order.", customer=self.customer
        )
        with self.assertRaises(ProtectedError):
            self.customer.delete()

    def test_str_representation(self):
        ticket = Ticket.objects.create(
            title="Login issue", description="Details here.", customer=self.customer
        )
        self.assertEqual(str(ticket), f"#{ticket.pk} Login issue")

    def test_default_ordering_is_newest_first(self):
        first = Ticket.objects.create(title="First", description="d", customer=self.customer)
        second = Ticket.objects.create(title="Second", description="d", customer=self.customer)
        tickets = list(Ticket.objects.all())
        self.assertEqual(tickets, [second, first])


class TicketAdminRegistrationTests(TestCase):
    def test_ticket_model_registered_in_admin(self):
        self.assertIn(Ticket, site._registry)

    def test_admin_list_display_includes_key_fields(self):
        admin_instance = site._registry[Ticket]
        for field in ("status", "priority", "customer", "assignee"):
            self.assertIn(field, admin_instance.list_display)


class TicketEventModelTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="cust2", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="agent2", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(
            title="Cannot access dashboard", description="Details here.", customer=self.customer
        )

    def test_create_event(self):
        event = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=self.agent,
            field_changed="status",
            old_value=Ticket.Status.OPEN,
            new_value=Ticket.Status.IN_PROGRESS,
        )
        self.assertEqual(event.ticket, self.ticket)
        self.assertEqual(event.actor, self.agent)
        self.assertIsNotNone(event.created_at)

    def test_old_value_defaults_to_empty_string(self):
        event = TicketEvent.objects.create(
            ticket=self.ticket, actor=self.agent, field_changed="assignee", new_value="agent2"
        )
        self.assertEqual(event.old_value, "")

    def test_events_ordered_chronologically(self):
        first = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=self.agent,
            field_changed="status",
            old_value=Ticket.Status.OPEN,
            new_value=Ticket.Status.IN_PROGRESS,
        )
        second = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=self.agent,
            field_changed="status",
            old_value=Ticket.Status.IN_PROGRESS,
            new_value=Ticket.Status.RESOLVED,
        )
        events = list(self.ticket.events.all())
        self.assertEqual(events, [first, second])

    def test_deleting_ticket_cascades_to_events(self):
        event = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=self.agent,
            field_changed="status",
            old_value=Ticket.Status.OPEN,
            new_value=Ticket.Status.IN_PROGRESS,
        )
        event_id = event.id
        self.ticket.delete()
        self.assertFalse(TicketEvent.objects.filter(id=event_id).exists())

    def test_deleting_actor_sets_null(self):
        event = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=self.agent,
            field_changed="status",
            old_value=Ticket.Status.OPEN,
            new_value=Ticket.Status.IN_PROGRESS,
        )
        self.agent.delete()
        event.refresh_from_db()
        self.assertIsNone(event.actor)

    def test_str_representation(self):
        event = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=self.agent,
            field_changed="status",
            old_value=Ticket.Status.OPEN,
            new_value=Ticket.Status.IN_PROGRESS,
        )
        self.assertEqual(
            str(event),
            f"Ticket #{self.ticket.pk} status: {Ticket.Status.OPEN} -> {Ticket.Status.IN_PROGRESS}",
        )


class TicketEventAdminRegistrationTests(TestCase):
    def test_ticket_event_registered_in_admin(self):
        self.assertIn(TicketEvent, site._registry)

    def test_change_permission_is_disabled(self):
        admin_instance = site._registry[TicketEvent]
        self.assertFalse(admin_instance.has_change_permission(request=None))

    def test_delete_permission_is_disabled(self):
        admin_instance = site._registry[TicketEvent]
        self.assertFalse(admin_instance.has_delete_permission(request=None))


class CommentModelTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="cust3", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="agent3", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(
            title="Cannot export report", description="Details here.", customer=self.customer
        )

    def test_create_comment(self):
        comment = Comment.objects.create(
            ticket=self.ticket, author=self.customer, body="Any update on this?"
        )
        self.assertEqual(comment.ticket, self.ticket)
        self.assertEqual(comment.author, self.customer)
        self.assertFalse(comment.is_internal)

    def test_create_internal_comment(self):
        comment = Comment.objects.create(
            ticket=self.ticket,
            author=self.agent,
            body="Escalating to backend team.",
            is_internal=True,
        )
        self.assertTrue(comment.is_internal)

    def test_timestamps_set_on_create(self):
        comment = Comment.objects.create(
            ticket=self.ticket, author=self.agent, body="Looking into it."
        )
        self.assertIsNotNone(comment.created_at)
        self.assertIsNotNone(comment.updated_at)

    def test_deleting_author_sets_null(self):
        comment = Comment.objects.create(ticket=self.ticket, author=self.agent, body="On it.")
        self.agent.delete()
        comment.refresh_from_db()
        self.assertIsNone(comment.author)

    def test_deleting_ticket_cascades_to_comments(self):
        comment = Comment.objects.create(ticket=self.ticket, author=self.customer, body="Thanks!")
        comment_id = comment.id
        self.ticket.delete()
        self.assertFalse(Comment.objects.filter(id=comment_id).exists())

    def test_comments_ordered_chronologically(self):
        first = Comment.objects.create(
            ticket=self.ticket, author=self.customer, body="First message"
        )
        second = Comment.objects.create(
            ticket=self.ticket, author=self.agent, body="Second message"
        )
        comments = list(self.ticket.comments.all())
        self.assertEqual(comments, [first, second])

    def test_str_representation(self):
        comment = Comment.objects.create(ticket=self.ticket, author=self.customer, body="Hello")
        self.assertEqual(str(comment), f"Comment #{comment.pk} on Ticket #{self.ticket.pk}")


class CommentAdminRegistrationTests(TestCase):
    def test_comment_model_registered_in_admin(self):
        self.assertIn(Comment, site._registry)

    def test_admin_list_display_includes_key_fields(self):
        admin_instance = site._registry[Comment]
        for field in ("ticket", "author", "is_internal"):
            self.assertIn(field, admin_instance.list_display)


TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AttachmentModelTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.customer = User.objects.create_user(
            username="cust4", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="agent4", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(
            title="Attachment issue", description="Details here.", customer=self.customer
        )
        self.comment = Comment.objects.create(
            ticket=self.ticket, author=self.customer, body="See attached."
        )

    def _file(self, name="test.txt", content=b"hello world"):
        return SimpleUploadedFile(name, content, content_type="text/plain")

    def test_create_attachment_on_ticket(self):
        attachment = Attachment.objects.create(
            ticket=self.ticket,
            file=self._file(),
            uploaded_by=self.customer,
            size=11,
            content_type="text/plain",
        )
        self.assertEqual(attachment.ticket, self.ticket)
        self.assertIsNone(attachment.comment)

    def test_create_attachment_on_comment(self):
        attachment = Attachment.objects.create(
            comment=self.comment,
            file=self._file(),
            uploaded_by=self.customer,
            size=11,
            content_type="text/plain",
        )
        self.assertEqual(attachment.comment, self.comment)
        self.assertIsNone(attachment.ticket)

    def test_clean_rejects_neither_parent_set(self):
        attachment = Attachment(
            file=self._file(), uploaded_by=self.customer, size=11, content_type="text/plain"
        )
        with self.assertRaises(ValidationError):
            attachment.clean()

    def test_clean_rejects_both_parents_set(self):
        attachment = Attachment(
            ticket=self.ticket,
            comment=self.comment,
            file=self._file(),
            uploaded_by=self.customer,
            size=11,
            content_type="text/plain",
        )
        with self.assertRaises(ValidationError):
            attachment.clean()

    def test_db_constraint_rejects_neither_parent(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Attachment.objects.create(
                    file=self._file(),
                    uploaded_by=self.customer,
                    size=11,
                    content_type="text/plain",
                )

    def test_db_constraint_rejects_both_parents(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Attachment.objects.create(
                    ticket=self.ticket,
                    comment=self.comment,
                    file=self._file(),
                    uploaded_by=self.customer,
                    size=11,
                    content_type="text/plain",
                )

    def test_deleting_uploaded_by_sets_null(self):
        attachment = Attachment.objects.create(
            ticket=self.ticket,
            file=self._file(),
            uploaded_by=self.agent,
            size=11,
            content_type="text/plain",
        )
        self.agent.delete()
        attachment.refresh_from_db()
        self.assertIsNone(attachment.uploaded_by)

    def test_deleting_ticket_cascades_to_attachment(self):
        attachment = Attachment.objects.create(
            ticket=self.ticket,
            file=self._file(),
            uploaded_by=self.customer,
            size=11,
            content_type="text/plain",
        )
        attachment_id = attachment.id
        self.ticket.delete()
        self.assertFalse(Attachment.objects.filter(id=attachment_id).exists())

    def test_deleting_comment_cascades_to_attachment(self):
        attachment = Attachment.objects.create(
            comment=self.comment,
            file=self._file(),
            uploaded_by=self.customer,
            size=11,
            content_type="text/plain",
        )
        attachment_id = attachment.id
        self.comment.delete()
        self.assertFalse(Attachment.objects.filter(id=attachment_id).exists())

    def test_str_representation(self):
        attachment = Attachment.objects.create(
            ticket=self.ticket,
            file=self._file(),
            uploaded_by=self.customer,
            size=11,
            content_type="text/plain",
        )
        self.assertEqual(str(attachment), f"Attachment #{attachment.pk} ({attachment.file.name})")


class AttachmentAdminRegistrationTests(TestCase):
    def test_attachment_model_registered_in_admin(self):
        self.assertIn(Attachment, site._registry)

    def test_admin_list_display_includes_key_fields(self):
        admin_instance = site._registry[Attachment]
        for field in ("ticket", "comment", "uploaded_by", "content_type", "size"):
            self.assertIn(field, admin_instance.list_display)


class TicketQuerysetScopingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer1 = User.objects.create_user(
            username="scopecust1", password="pass12345", role=User.Role.CUSTOMER
        )
        self.customer2 = User.objects.create_user(
            username="scopecust2", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="scopeagent1", password="pass12345", role=User.Role.AGENT
        )
        self.ticket1 = Ticket.objects.create(
            title="Ticket one", description="d", customer=self.customer1
        )
        self.ticket2 = Ticket.objects.create(
            title="Ticket two", description="d", customer=self.customer2
        )

    def _auth(self, user):
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_unauthenticated_list_rejected(self):
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, 401)

    def test_customer_list_only_shows_own_tickets(self):
        self._auth(self.customer1)
        response = self.client.get("/api/tickets/")
        self.assertEqual(response.status_code, 200)
        ids = [t["id"] for t in response.data]
        self.assertEqual(ids, [self.ticket1.id])

    def test_agent_list_shows_all_tickets(self):
        self._auth(self.agent)
        response = self.client.get("/api/tickets/")
        ids = {t["id"] for t in response.data}
        self.assertEqual(ids, {self.ticket1.id, self.ticket2.id})

    def test_customer_can_retrieve_own_ticket(self):
        self._auth(self.customer1)
        response = self.client.get(f"/api/tickets/{self.ticket1.id}/")
        self.assertEqual(response.status_code, 200)

    def test_customer_cannot_retrieve_other_customers_ticket(self):
        self._auth(self.customer1)
        response = self.client.get(f"/api/tickets/{self.ticket2.id}/")
        self.assertEqual(response.status_code, 404)

    def test_agent_can_retrieve_any_ticket(self):
        self._auth(self.agent)
        response = self.client.get(f"/api/tickets/{self.ticket1.id}/")
        self.assertEqual(response.status_code, 200)

    def test_customer_create_ticket_assigns_self_as_customer(self):
        self._auth(self.customer1)
        response = self.client.post(
            "/api/tickets/", {"title": "New ticket", "description": "details"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["customer"], self.customer1.id)

    def test_customer_cannot_override_customer_field_on_create(self):
        self._auth(self.customer1)
        response = self.client.post(
            "/api/tickets/",
            {"title": "New ticket", "description": "details", "customer": self.customer2.id},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["customer"], self.customer1.id)
