from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from rest_framework.test import APIClient

from core.tests.factories import SiteFactory
from tickets.models import Attachment, Comment, Ticket

WIDGET_CONFIG_URL = "/api/widget/config/"
CONVERSATIONS_URL = "/api/widget/conversations/"


def _messages_url(ticket_id):
    return f"/api/widget/conversations/{ticket_id}/messages/"


def _read_url(ticket_id):
    return f"/api/widget/conversations/{ticket_id}/read/"


def _attachments_url(ticket_id):
    return f"/api/widget/conversations/{ticket_id}/attachments/"


def _download_url(attachment_id):
    return f"/api/widget/attachments/{attachment_id}/download/"


class WidgetConfigTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.site = SiteFactory(allowed_origins=["https://example.com"])

    def test_config_returns_site_settings(self):
        res = self.client.get(
            f"{WIDGET_CONFIG_URL}?key={self.site.key}", HTTP_ORIGIN="https://example.com"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["name"], self.site.name)

    def test_config_rejects_invalid_key(self):
        res = self.client.get(f"{WIDGET_CONFIG_URL}?key=invalid", HTTP_ORIGIN="https://example.com")
        self.assertEqual(res.status_code, 404)

    def test_config_rejects_disallowed_origin(self):
        res = self.client.get(
            f"{WIDGET_CONFIG_URL}?key={self.site.key}", HTTP_ORIGIN="https://evil.com"
        )
        self.assertEqual(res.status_code, 403)


class WidgetConversationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.site = SiteFactory(allowed_origins=["https://example.com"])

    def test_start_conversation_creates_visitor_and_ticket(self):
        res = self.client.post(
            CONVERSATIONS_URL,
            {"site_key": self.site.key, "body": "Hello", "name": "Test"},
            HTTP_ORIGIN="https://example.com",
        )
        self.assertEqual(res.status_code, 201)
        self.assertIn("token", res.data)
        self.assertIn("conversation", res.data)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_start_conversation_enforces_required_name(self):
        self.site.require_name = True
        self.site.save()
        res = self.client.post(
            CONVERSATIONS_URL,
            {"site_key": self.site.key, "body": "Hello"},
            HTTP_ORIGIN="https://example.com",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.data["error"]["details"])

    def test_resume_conversation_with_token(self):
        res1 = self.client.post(
            CONVERSATIONS_URL,
            {"site_key": self.site.key, "body": "Hello"},
            HTTP_ORIGIN="https://example.com",
        )
        token = res1.data["token"]
        ticket_id = res1.data["conversation"]["id"]

        self.client.credentials(HTTP_X_VISITOR_TOKEN=token, HTTP_ORIGIN="https://example.com")
        res2 = self.client.post(
            CONVERSATIONS_URL,
            {"body": "Second message"},
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data["conversation"]["id"], ticket_id)
        self.assertEqual(Comment.objects.count(), 2)

    def test_rejects_disallowed_origin(self):
        res = self.client.post(
            CONVERSATIONS_URL,
            {"site_key": self.site.key, "body": "Hello"},
            HTTP_ORIGIN="https://evil.com",
        )
        self.assertEqual(res.status_code, 403)


class WidgetMessageTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.site = SiteFactory(allowed_origins=["https://example.com"])
        res = self.client.post(
            CONVERSATIONS_URL,
            {"site_key": self.site.key, "body": "Hello"},
            HTTP_ORIGIN="https://example.com",
        )
        self.token = res.data["token"]
        self.ticket_id = res.data["conversation"]["id"]
        self.client.credentials(HTTP_X_VISITOR_TOKEN=self.token, HTTP_ORIGIN="https://example.com")

    def test_list_messages(self):
        res = self.client.get(_messages_url(self.ticket_id))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["results"]), 1)

    def test_post_message(self):
        res = self.client.post(_messages_url(self.ticket_id), {"body": "Another one"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Comment.objects.count(), 2)

    def test_post_message_dedupes_by_client_msg_id(self):
        res1 = self.client.post(
            _messages_url(self.ticket_id), {"body": "Msg", "client_msg_id": "abc"}
        )
        res2 = self.client.post(
            _messages_url(self.ticket_id), {"body": "Msg", "client_msg_id": "abc"}
        )
        self.assertEqual(res1.status_code, 201)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(Comment.objects.count(), 2)

    def test_cannot_access_other_conversation(self):
        other_site = SiteFactory(allowed_origins=["https://example.com"])
        self.client.credentials()
        other_res = self.client.post(
            CONVERSATIONS_URL,
            {"site_key": other_site.key, "body": "Hi"},
            HTTP_ORIGIN="https://example.com",
        )
        other_id = other_res.data["conversation"]["id"]

        self.client.credentials(HTTP_X_VISITOR_TOKEN=self.token, HTTP_ORIGIN="https://example.com")
        res = self.client.get(_messages_url(other_id))
        self.assertEqual(res.status_code, 404)


class WidgetReadTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.site = SiteFactory(allowed_origins=["https://example.com"])
        res = self.client.post(
            CONVERSATIONS_URL,
            {"site_key": self.site.key, "body": "Hello"},
            HTTP_ORIGIN="https://example.com",
        )
        self.token = res.data["token"]
        self.ticket_id = res.data["conversation"]["id"]
        self.client.credentials(HTTP_X_VISITOR_TOKEN=self.token, HTTP_ORIGIN="https://example.com")

    def test_mark_read(self):
        msg_res = self.client.post(_messages_url(self.ticket_id), {"body": "Test"})
        msg_id = msg_res.data["id"]
        res = self.client.post(_read_url(self.ticket_id), {"last_read_comment_id": msg_id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["last_read_comment_id"], msg_id)


class WidgetAttachmentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.site = SiteFactory(allowed_origins=["https://example.com"])
        res = self.client.post(
            CONVERSATIONS_URL,
            {"site_key": self.site.key, "body": "Hello"},
            HTTP_ORIGIN="https://example.com",
        )
        self.token = res.data["token"]
        self.ticket_id = res.data["conversation"]["id"]
        self.client.credentials(HTTP_X_VISITOR_TOKEN=self.token, HTTP_ORIGIN="https://example.com")

    def test_upload_attachment(self):
        f = SimpleUploadedFile("test.txt", b"hello", content_type="text/plain")
        res = self.client.post(
            _attachments_url(self.ticket_id), {"file": f, "body": "See attached"}
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Attachment.objects.count(), 1)

    def test_download_attachment(self):
        f = SimpleUploadedFile("test.txt", b"hello", content_type="text/plain")
        up_res = self.client.post(
            _attachments_url(self.ticket_id), {"file": f, "body": "See attached"}
        )
        att_id = up_res.data["attachments"][0]["id"]
        res = self.client.get(_download_url(att_id))
        self.assertEqual(res.status_code, 200)
        self.assertIn("url", res.data)


class WidgetReplyReopenTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.site = SiteFactory(allowed_origins=["https://example.com"])
        res = self.client.post(
            CONVERSATIONS_URL,
            {"site_key": self.site.key, "body": "Hello"},
            HTTP_ORIGIN="https://example.com",
        )
        self.token = res.data["token"]
        self.ticket_id = res.data["conversation"]["id"]
        self.client.credentials(HTTP_X_VISITOR_TOKEN=self.token, HTTP_ORIGIN="https://example.com")

    def _make_waiting(self):
        Ticket.objects.filter(pk=self.ticket_id).update(status=Ticket.Status.WAITING_ON_CUSTOMER)

    def test_a_visitor_message_moves_a_waiting_conversation_to_in_progress(self):
        self._make_waiting()
        res = self.client.post(_messages_url(self.ticket_id), {"body": "Still there?"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Ticket.objects.get(pk=self.ticket_id).status, Ticket.Status.IN_PROGRESS)

    def test_a_visitor_attachment_moves_a_waiting_conversation_to_in_progress(self):
        self._make_waiting()
        upload = SimpleUploadedFile("test.txt", b"hello", content_type="text/plain")
        res = self.client.post(
            _attachments_url(self.ticket_id), {"file": upload, "body": "See attached"}
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Ticket.objects.get(pk=self.ticket_id).status, Ticket.Status.IN_PROGRESS)

    def test_the_conversation_endpoint_moves_a_waiting_conversation_to_in_progress(self):
        self._make_waiting()
        res = self.client.post(CONVERSATIONS_URL, {"body": "Still there?"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Ticket.objects.get(pk=self.ticket_id).status, Ticket.Status.IN_PROGRESS)
