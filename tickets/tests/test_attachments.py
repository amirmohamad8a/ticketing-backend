import shutil
import tempfile

from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from tickets.models import Attachment, Ticket

TEST_MEDIA_ROOT = tempfile.mkdtemp()


def _auth(client, user):
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


def _file(name="test.txt", content=b"hello world", content_type="text/plain"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, content, content_type=content_type)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AttachmentUploadValidationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            username="au_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        self.other_customer = User.objects.create_user(
            username="au_cust2", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="au_agent", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)

    def _auth(self, user):
        _auth(self.client, user)

    def test_unauthenticated_upload_rejected(self):
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/attachments/", {"file": _file()}
        )
        self.assertEqual(response.status_code, 401)

    def test_customer_can_upload_allowed_file_to_own_ticket(self):
        self._auth(self.customer)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/attachments/", {"file": _file()}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["size"], len(b"hello world"))
        self.assertEqual(response.data["content_type"], "text/plain")
        self.assertEqual(response.data["ticket"], self.ticket.id)

    def test_uploaded_by_is_requesting_user_not_request_body(self):
        self._auth(self.customer)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/attachments/",
            {"file": _file(), "uploaded_by": self.agent.id},
        )
        self.assertEqual(response.status_code, 201)
        attachment = Attachment.objects.get(id=response.data["id"])
        self.assertEqual(attachment.uploaded_by, self.customer)

    def test_size_and_content_type_derived_from_actual_file_not_body(self):
        self._auth(self.customer)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/attachments/",
            {"file": _file(), "size": 1, "content_type": "application/x-evil"},
        )
        self.assertEqual(response.status_code, 201)
        attachment = Attachment.objects.get(id=response.data["id"])
        self.assertEqual(attachment.size, len(b"hello world"))
        self.assertEqual(attachment.content_type, "text/plain")

    def test_oversized_file_rejected_with_400(self):
        self._auth(self.customer)
        oversized = _file(content=b"x" * (Attachment.MAX_SIZE_BYTES + 1))
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/attachments/", {"file": oversized}
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Attachment.objects.filter(ticket=self.ticket).exists())

    def test_file_at_exact_size_limit_is_allowed(self):
        self._auth(self.customer)
        exact = _file(content=b"x" * Attachment.MAX_SIZE_BYTES)
        response = self.client.post(f"/api/tickets/{self.ticket.id}/attachments/", {"file": exact})
        self.assertEqual(response.status_code, 201)

    def test_disallowed_content_type_rejected_with_400(self):
        self._auth(self.customer)
        script = _file(name="script.sh", content=b"#!/bin/sh", content_type="application/x-sh")
        response = self.client.post(f"/api/tickets/{self.ticket.id}/attachments/", {"file": script})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Attachment.objects.filter(ticket=self.ticket).exists())

    def test_allowed_content_type_pdf_accepted(self):
        self._auth(self.customer)
        pdf = _file(name="doc.pdf", content=b"%PDF-1.4", content_type="application/pdf")
        response = self.client.post(f"/api/tickets/{self.ticket.id}/attachments/", {"file": pdf})
        self.assertEqual(response.status_code, 201)

    def test_missing_file_rejected_with_400(self):
        self._auth(self.customer)
        response = self.client.post(f"/api/tickets/{self.ticket.id}/attachments/", {})
        self.assertEqual(response.status_code, 400)

    def test_agent_can_upload_to_any_ticket(self):
        self._auth(self.agent)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/attachments/", {"file": _file()}
        )
        self.assertEqual(response.status_code, 201)

    def test_agent_can_upload_a_ticket_attachment_hidden_from_customers(self):
        self._auth(self.agent)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/attachments/", {"file": _file(), "is_internal": True}
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["is_internal"])
        self.assertTrue(Attachment.objects.get(id=response.data["id"]).is_internal)

    def test_customer_cannot_mark_a_ticket_attachment_internal(self):
        self._auth(self.customer)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/attachments/", {"file": _file(), "is_internal": True}
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["is_internal"])
        self.assertFalse(Attachment.objects.get(id=response.data["id"]).is_internal)

    def test_other_customer_cannot_upload_to_ticket_they_dont_own(self):
        self._auth(self.other_customer)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/attachments/", {"file": _file()}
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Attachment.objects.filter(ticket=self.ticket).exists())


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AttachmentListingTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            username="al_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        self.other_customer = User.objects.create_user(
            username="al_cust2", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="al_agent", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)
        self.attachment = Attachment.objects.create(
            ticket=self.ticket,
            file=_file(),
            uploaded_by=self.customer,
            size=11,
            content_type="text/plain",
        )

    def _auth(self, user):
        _auth(self.client, user)

    def test_unauthenticated_list_rejected(self):
        response = self.client.get(f"/api/tickets/{self.ticket.id}/attachments/")
        self.assertEqual(response.status_code, 401)

    def test_owner_can_list_own_attachments(self):
        self._auth(self.customer)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/attachments/")
        self.assertEqual(response.status_code, 200)
        ids = [a["id"] for a in response.data]
        self.assertEqual(ids, [self.attachment.id])

    def test_agent_can_list_any_ticket_attachments(self):
        self._auth(self.agent)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/attachments/")
        self.assertEqual(response.status_code, 200)

    def test_other_customer_cannot_list_attachments(self):
        self._auth(self.other_customer)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/attachments/")
        self.assertEqual(response.status_code, 404)

    def test_customer_cannot_see_a_staff_internal_ticket_attachment(self):
        internal = Attachment.objects.create(
            ticket=self.ticket,
            file=_file(name="private.txt"),
            uploaded_by=self.agent,
            size=11,
            content_type="text/plain",
            is_internal=True,
        )
        self._auth(self.customer)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/attachments/")
        self.assertEqual([a["id"] for a in response.data], [self.attachment.id])
        self.assertEqual(
            self.client.get(f"/api/attachments/{internal.id}/download/").status_code, 404
        )

    def test_agent_sees_a_staff_internal_ticket_attachment(self):
        internal = Attachment.objects.create(
            ticket=self.ticket,
            file=_file(name="private.txt"),
            uploaded_by=self.agent,
            size=11,
            content_type="text/plain",
            is_internal=True,
        )
        self._auth(self.agent)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/attachments/")
        self.assertEqual({a["id"] for a in response.data}, {self.attachment.id, internal.id})
