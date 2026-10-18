import shutil
import tempfile

from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests import read_streaming_body
from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    AttachmentFactory,
    CommentFactory,
    TicketFactory,
    UserFactory,
)

TEST_MEDIA_ROOT = tempfile.mkdtemp()


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _url(attachment):
    return f"/api/attachments/{attachment.id}/download/"


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AttachmentDownloadTests(TestCase):
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
        self.internal_comment = CommentFactory(
            ticket=self.ticket, author=self.agent, is_internal=True
        )
        self.ticket_attachment = AttachmentFactory(ticket=self.ticket, uploaded_by=self.customer)
        self.public_attachment = AttachmentFactory(
            on_comment=True, comment=self.public_comment, uploaded_by=self.customer
        )
        self.internal_attachment = AttachmentFactory(
            on_comment=True, comment=self.internal_comment, uploaded_by=self.agent
        )

    def _get(self, user, attachment):
        return _client_for(user).get(_url(attachment))

    def _fetch(self, link):
        response = APIClient().get(link["url"])
        self.assertEqual(response.status_code, 200)
        return read_streaming_body(response)

    def test_unauthenticated_request_is_rejected(self):
        response = APIClient().get(_url(self.ticket_attachment))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "not_authenticated")

    def test_owner_gets_a_link_for_a_ticket_attachment(self):
        response = self._get(self.customer, self.ticket_attachment)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"url", "expires_in"})
        self.assertGreater(response.data["expires_in"], 0)
        self.assertEqual(self._fetch(response.data), b"hello world")

    def test_owner_gets_a_link_for_a_public_comment_attachment(self):
        response = self._get(self.customer, self.public_attachment)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._fetch(response.data), b"hello world")

    def test_staff_get_links_for_every_attachment(self):
        attachments = (self.ticket_attachment, self.public_attachment, self.internal_attachment)
        for user in (self.agent, self.admin):
            for attachment in attachments:
                with self.subTest(role=user.role, attachment=attachment.id):
                    self.assertEqual(self._get(user, attachment).status_code, 200)

    def test_customer_gets_404_for_an_internal_comment_attachment(self):
        response = self._get(self.customer, self.internal_attachment)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "not_found")

    def test_another_customer_gets_404_for_every_attachment_of_the_ticket(self):
        attachments = (self.ticket_attachment, self.public_attachment, self.internal_attachment)
        for attachment in attachments:
            with self.subTest(attachment=attachment.id):
                self.assertEqual(self._get(self.other_customer, attachment).status_code, 404)

    def test_deleted_ticket_hides_its_attachments_from_everyone(self):
        self.ticket.delete()
        attachments = (self.ticket_attachment, self.public_attachment, self.internal_attachment)
        for user in (self.customer, self.agent, self.admin):
            for attachment in attachments:
                with self.subTest(role=user.role, attachment=attachment.id):
                    self.assertEqual(self._get(user, attachment).status_code, 404)

    def test_restored_ticket_makes_its_attachments_reachable_again(self):
        self.ticket.delete()
        self.ticket.restore()
        self.assertEqual(self._get(self.customer, self.ticket_attachment).status_code, 200)

    def test_unknown_attachment_returns_404(self):
        response = _client_for(self.admin).get("/api/attachments/999999/download/")
        self.assertEqual(response.status_code, 404)

    def test_only_get_is_allowed(self):
        response = _client_for(self.agent).post(_url(self.ticket_attachment))
        self.assertEqual(response.status_code, 405)

    def test_listing_exposes_download_url_and_hides_the_file_field(self):
        response = _client_for(self.agent).get(f"/api/tickets/{self.ticket.id}/attachments/")
        self.assertEqual(response.status_code, 200)
        row = response.data[0]
        self.assertNotIn("file", row)
        expected = f"http://testserver/api/attachments/{self.ticket_attachment.id}/download/"
        self.assertEqual(row["download_url"], expected)

    def test_comment_attachment_listing_exposes_download_url(self):
        url = f"/api/tickets/{self.ticket.id}/comments/{self.public_comment.id}/attachments/"
        response = _client_for(self.customer).get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("file", response.data[0])
        self.assertTrue(response.data[0]["download_url"].endswith(_url(self.public_attachment)))

    def test_upload_response_exposes_download_url_and_hides_the_file_field(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("note.txt", b"fresh", content_type="text/plain")
        response = _client_for(self.customer).post(
            f"/api/tickets/{self.ticket.id}/attachments/", {"file": upload}
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("file", response.data)
        link = _client_for(self.customer).get(f"/api/attachments/{response.data['id']}/download/")
        self.assertEqual(link.status_code, 200)
        self.assertEqual(self._fetch(link.data), b"fresh")
        self.assertTrue(response.data["download_url"].endswith(f"/{response.data['id']}/download/"))


class AttachmentDownloadSchemaTests(TestCase):
    def test_route_is_documented_under_the_attachments_tag(self):
        response = APIClient().get("/api/schema/?format=json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        matching = [path for path in paths if path.startswith("/api/attachments/")]
        self.assertEqual(len(matching), 1)
        self.assertEqual(paths[matching[0]]["get"]["tags"], ["Attachments"])
        self.assertFalse(any(path.startswith("/api/downloads/") for path in paths))
