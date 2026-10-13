import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    AttachmentFactory,
    CommentFactory,
    TicketFactory,
    UserFactory,
)
from tickets.models import Attachment, Comment, Ticket

TEST_MEDIA_ROOT = tempfile.mkdtemp()


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _file(name="test.txt", content=b"hello world", content_type="text/plain"):
    return SimpleUploadedFile(name, content, content_type=content_type)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class CommentAttachmentFixture(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.customer = UserFactory()
        self.other_customer = UserFactory()
        self.agent = AgentFactory()
        self.admin = AdminFactory()
        self.ticket = TicketFactory(customer=self.customer)
        self.public_comment = CommentFactory(ticket=self.ticket, author=self.customer)
        self.agent_comment = CommentFactory(ticket=self.ticket, author=self.agent)
        self.internal_comment = CommentFactory(
            ticket=self.ticket, author=self.agent, is_internal=True
        )
        self.public_attachment = AttachmentFactory(
            on_comment=True, comment=self.public_comment, uploaded_by=self.customer
        )
        self.internal_attachment = AttachmentFactory(
            on_comment=True, comment=self.internal_comment, uploaded_by=self.agent
        )

    def _url(self, comment, ticket=None):
        ticket = ticket or self.ticket
        return f"/api/tickets/{ticket.id}/comments/{comment.id}/attachments/"

    def _count(self, comment):
        return Attachment.objects.filter(comment=comment).count()


class CommentAttachmentListTests(CommentAttachmentFixture):
    def _ids(self, response):
        return [attachment["id"] for attachment in response.data]

    def test_unauthenticated_requests_are_rejected(self):
        client = APIClient()
        url = self._url(self.public_comment)
        self.assertEqual(client.get(url).status_code, 401)
        self.assertEqual(client.post(url, {"file": _file()}).status_code, 401)

    def test_customer_can_list_attachments_of_a_public_comment(self):
        response = _client_for(self.customer).get(self._url(self.public_comment))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), [self.public_attachment.id])
        self.assertEqual(response.data[0]["comment"], self.public_comment.id)
        self.assertIsNone(response.data[0]["ticket"])

    def test_staff_can_list_attachments_of_an_internal_comment(self):
        for user in (self.agent, self.admin):
            with self.subTest(role=user.role):
                response = _client_for(user).get(self._url(self.internal_comment))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self._ids(response), [self.internal_attachment.id])

    def test_customer_gets_404_for_an_internal_comment(self):
        response = _client_for(self.customer).get(self._url(self.internal_comment))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "not_found")
        self.assertNotIn(str(self.internal_attachment.id), str(response.data))

    def test_customer_cannot_upload_to_an_internal_comment(self):
        response = _client_for(self.customer).post(
            self._url(self.internal_comment), {"file": _file()}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._count(self.internal_comment), 1)

    def test_another_customer_gets_404(self):
        client = _client_for(self.other_customer)
        self.assertEqual(client.get(self._url(self.public_comment)).status_code, 404)
        self.assertEqual(
            client.post(self._url(self.public_comment), {"file": _file()}).status_code, 404
        )
        self.assertEqual(self._count(self.public_comment), 1)

    def test_comment_from_another_ticket_is_not_reachable(self):
        other_ticket = TicketFactory(customer=self.customer)
        other_comment = CommentFactory(ticket=other_ticket, author=self.customer)
        url = self._url(other_comment, ticket=self.ticket)
        for user in (self.customer, self.agent, self.admin):
            with self.subTest(role=user.role):
                self.assertEqual(_client_for(user).get(url).status_code, 404)

    def test_unknown_comment_returns_404(self):
        url = f"/api/tickets/{self.ticket.id}/comments/999999/attachments/"
        self.assertEqual(_client_for(self.agent).get(url).status_code, 404)

    def test_deleted_ticket_hides_its_comment_attachments(self):
        self.ticket.delete()
        for user in (self.customer, self.agent, self.admin):
            with self.subTest(role=user.role):
                response = _client_for(user).get(self._url(self.public_comment))
                self.assertEqual(response.status_code, 404)

    def test_each_comment_lists_only_its_own_attachments(self):
        response = _client_for(self.agent).get(self._url(self.agent_comment))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_ticket_level_list_does_not_include_comment_attachments(self):
        ticket_attachment = AttachmentFactory(ticket=self.ticket, uploaded_by=self.customer)
        response = _client_for(self.agent).get(f"/api/tickets/{self.ticket.id}/attachments/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), [ticket_attachment.id])

    def test_non_authors_can_still_read_a_public_comments_attachments(self):
        response = _client_for(self.customer).get(self._url(self.agent_comment))
        self.assertEqual(response.status_code, 200)


class CommentAttachmentUploadTests(CommentAttachmentFixture):
    def test_customer_can_upload_to_their_own_public_comment(self):
        response = _client_for(self.customer).post(
            self._url(self.public_comment), {"file": _file()}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["comment"], self.public_comment.id)
        self.assertIsNone(response.data["ticket"])
        self.assertEqual(response.data["uploaded_by"], self.customer.id)
        self.assertEqual(response.data["size"], len(b"hello world"))
        self.assertEqual(response.data["content_type"], "text/plain")
        self.assertEqual(self._count(self.public_comment), 2)

    def test_agent_can_upload_to_their_own_internal_and_public_comments(self):
        client = _client_for(self.agent)
        for comment in (self.internal_comment, self.agent_comment):
            with self.subTest(internal=comment.is_internal):
                response = client.post(self._url(comment), {"file": _file()})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data["comment"], comment.id)

    def test_uploaded_internal_attachment_stays_hidden_from_customers(self):
        _client_for(self.agent).post(self._url(self.internal_comment), {"file": _file()})
        self.assertEqual(self._count(self.internal_comment), 2)
        response = _client_for(self.customer).get(self._url(self.internal_comment))
        self.assertEqual(response.status_code, 404)

    def test_owner_fields_come_from_the_request_and_the_file(self):
        response = _client_for(self.customer).post(
            self._url(self.public_comment),
            {
                "file": _file(),
                "uploaded_by": self.agent.id,
                "size": 1,
                "content_type": "application/x-evil",
                "ticket": self.ticket.id,
            },
        )
        self.assertEqual(response.status_code, 201)
        attachment = Attachment.objects.get(id=response.data["id"])
        self.assertEqual(attachment.uploaded_by, self.customer)
        self.assertEqual(attachment.size, len(b"hello world"))
        self.assertEqual(attachment.content_type, "text/plain")
        self.assertIsNone(attachment.ticket)
        self.assertEqual(attachment.comment, self.public_comment)

    def test_oversized_file_is_rejected_with_400(self):
        oversized = _file(content=b"x" * (Attachment.MAX_SIZE_BYTES + 1))
        response = _client_for(self.customer).post(
            self._url(self.public_comment), {"file": oversized}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertEqual(self._count(self.public_comment), 1)

    def test_disallowed_content_type_is_rejected_with_400(self):
        script = _file(name="script.sh", content=b"#!/bin/sh", content_type="application/x-sh")
        response = _client_for(self.customer).post(self._url(self.public_comment), {"file": script})
        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.data["error"]["details"])
        self.assertEqual(self._count(self.public_comment), 1)

    def test_allowed_content_type_pdf_is_accepted(self):
        pdf = _file(name="doc.pdf", content=b"%PDF-1.4", content_type="application/pdf")
        response = _client_for(self.customer).post(self._url(self.public_comment), {"file": pdf})
        self.assertEqual(response.status_code, 201)

    def test_missing_file_is_rejected_with_400(self):
        response = _client_for(self.customer).post(self._url(self.public_comment), {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._count(self.public_comment), 1)

    def test_customer_can_still_upload_after_the_ticket_left_open(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(status=Ticket.Status.IN_PROGRESS)
        response = _client_for(self.customer).post(
            self._url(self.public_comment), {"file": _file()}
        )
        self.assertEqual(response.status_code, 201)


class CommentAttachmentAuthorRuleTests(CommentAttachmentFixture):
    def _assert_forbidden(self, user, comment):
        before = self._count(comment)
        response = _client_for(user).post(self._url(comment), {"file": _file()})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "permission_denied")
        self.assertEqual(self._count(comment), before)

    def test_customer_cannot_attach_to_an_agents_public_comment(self):
        self._assert_forbidden(self.customer, self.agent_comment)

    def test_agent_cannot_attach_to_a_customers_comment(self):
        self._assert_forbidden(self.agent, self.public_comment)

    def test_admin_cannot_attach_to_someone_elses_comment(self):
        self._assert_forbidden(self.admin, self.public_comment)
        self._assert_forbidden(self.admin, self.internal_comment)

    def test_nobody_can_attach_to_a_system_comment(self):
        system_comment = CommentFactory(
            ticket=self.ticket,
            author=None,
            visitor=None,
            kind=Comment.Kind.SYSTEM,
        )
        for user in (self.customer, self.agent, self.admin):
            with self.subTest(role=user.role):
                self._assert_forbidden(user, system_comment)
