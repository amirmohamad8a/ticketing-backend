import io
import shutil
import tempfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import CommentFactory, TicketFactory, UserFactory
from core.uploads import DOCX_CONTENT_TYPE, ZIP_CONTENT_TYPE
from tickets.models import Attachment

TEST_MEDIA_ROOT = tempfile.mkdtemp()

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF_BYTES = b"GIF89a" + b"\x00" * 32
PDF_BYTES = b"%PDF-1.4\n%%EOF"
SCRIPT_BYTES = b"#!/bin/sh\necho hello\n"


def _zip_bytes(*names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "content")
    return buffer.getvalue()


DOCX_BYTES = _zip_bytes("[Content_Types].xml", "word/document.xml")
ZIP_BYTES = _zip_bytes("notes.txt", "photos/cat.png")

GENUINE_FILES = [
    ("image.png", PNG_BYTES, "image/png"),
    ("photo.jpg", JPEG_BYTES, "image/jpeg"),
    ("anim.gif", GIF_BYTES, "image/gif"),
    ("doc.pdf", PDF_BYTES, "application/pdf"),
    ("note.txt", b"hello world", "text/plain"),
    ("letter.docx", DOCX_BYTES, DOCX_CONTENT_TYPE),
    ("bundle.zip", ZIP_BYTES, ZIP_CONTENT_TYPE),
]


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AttachmentSafetyFixture(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.customer = UserFactory()
        self.ticket = TicketFactory(customer=self.customer)
        self.comment = CommentFactory(ticket=self.ticket, author=self.customer)
        self.client = _client_for(self.customer)
        self.ticket_url = f"/api/tickets/{self.ticket.id}/attachments/"
        self.comment_url = f"/api/tickets/{self.ticket.id}/comments/{self.comment.id}/attachments/"

    def _post(self, content, name="upload.txt", content_type="text/plain", url=None, extra=None):
        upload = SimpleUploadedFile(name, content, content_type=content_type)
        data = {"file": upload, **(extra or {})}
        return self.client.post(url or self.ticket_url, data)

    def _stored(self, response):
        return Attachment.objects.get(id=response.data["id"])


class AttachmentContentVerificationTests(AttachmentSafetyFixture):
    def _assert_rejected(self, response):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("file", response.data["error"]["details"])
        self.assertEqual(Attachment.objects.count(), 0)

    def test_shell_script_renamed_to_png_is_rejected(self):
        response = self._post(SCRIPT_BYTES, name="photo.png", content_type="image/png")
        self._assert_rejected(response)

    def test_png_labelled_as_pdf_is_rejected(self):
        response = self._post(PNG_BYTES, name="report.pdf", content_type="application/pdf")
        self._assert_rejected(response)

    def test_every_genuine_file_is_rejected_under_any_other_allowed_type(self):
        for name, content, actual in GENUINE_FILES:
            for declared in sorted(Attachment.ALLOWED_CONTENT_TYPES - {actual}):
                with self.subTest(actual=actual, declared=declared):
                    response = self._post(content, name=name, content_type=declared)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("file", response.data["error"]["details"])
        self.assertEqual(Attachment.objects.count(), 0)

    def test_unrecognised_binary_labelled_as_text_is_rejected(self):
        self._assert_rejected(self._post(b"plain start \xff\xfe\xfd"))

    def test_corrupt_zip_is_rejected(self):
        response = self._post(
            b"PK\x03\x04" + b"not really a zip", name="bundle.zip", content_type=ZIP_CONTENT_TYPE
        )
        self._assert_rejected(response)

    def test_disallowed_declared_type_is_still_rejected_first(self):
        response = self._post(SCRIPT_BYTES, name="run.sh", content_type="application/x-sh")
        self._assert_rejected(response)

    def test_comment_attachments_get_the_same_check(self):
        response = self._post(
            PNG_BYTES, name="report.pdf", content_type="application/pdf", url=self.comment_url
        )
        self._assert_rejected(response)

    def test_every_genuine_file_is_accepted_under_its_real_type(self):
        for name, content, actual in GENUINE_FILES:
            with self.subTest(content_type=actual):
                response = self._post(content, name=name, content_type=actual)
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data["content_type"], actual)
        self.assertEqual(Attachment.objects.count(), len(GENUINE_FILES))


class AttachmentStoredNameTests(AttachmentSafetyFixture):
    def test_stored_name_is_random_and_never_contains_the_uploaded_name(self):
        response = self._post(b"hello", name="secret-report.txt")
        self.assertEqual(response.status_code, 201)
        name = self._stored(response).file.name
        self.assertNotIn("secret-report", name)
        self.assertRegex(name, r"^attachments/\d{4}/\d{2}/\d{2}/[0-9a-f]{32}\.txt$")

    def test_extension_follows_the_verified_content_not_the_uploaded_name(self):
        response = self._post(PNG_BYTES, name="payload.sh", content_type="image/png")
        self.assertEqual(response.status_code, 201)
        name = self._stored(response).file.name
        self.assertTrue(name.endswith(".png"))
        self.assertNotIn("payload", name)

    def test_the_same_upload_twice_gets_two_different_stored_names(self):
        first = self._stored(self._post(b"hello", name="same.txt"))
        second = self._stored(self._post(b"hello", name="same.txt"))
        self.assertNotEqual(first.file.name, second.file.name)

    def test_comment_attachments_use_random_names_too(self):
        response = self._post(b"hello", name="secret-note.txt", url=self.comment_url)
        self.assertEqual(response.status_code, 201)
        name = self._stored(response).file.name
        self.assertNotIn("secret-note", name)
        self.assertRegex(name, r"^attachments/\d{4}/\d{2}/\d{2}/[0-9a-f]{32}\.txt$")

    def test_original_name_is_kept_and_listed_for_display(self):
        response = self._post(b"hello", name="my report.txt")
        self.assertEqual(response.data["original_name"], "my report.txt")
        self.assertEqual(self._stored(response).original_name, "my report.txt")
        listing = self.client.get(self.ticket_url)
        self.assertEqual(listing.data[0]["original_name"], "my report.txt")

    def test_original_name_cannot_be_set_through_the_request(self):
        response = self._post(b"hello", name="real.txt", extra={"original_name": "forged.exe"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["original_name"], "real.txt")


class AttachmentDownloadNameTests(AttachmentSafetyFixture):
    def _download(self, response):
        link = self.client.get(f"/api/attachments/{response.data['id']}/download/")
        self.assertEqual(link.status_code, 200)
        download = APIClient().get(link.data["url"])
        self.assertEqual(download.status_code, 200)
        b"".join(download.streaming_content)
        return download

    def test_download_is_forced_and_carries_the_original_name(self):
        download = self._download(self._post(b"hello", name="my report.txt"))
        self.assertEqual(download["Content-Disposition"], 'attachment; filename="my report.txt"')
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")
        self.assertEqual(download["Content-Type"], "text/plain")

    def test_images_are_downloaded_as_attachments_too(self):
        response = self._post(PNG_BYTES, name="shot.png", content_type="image/png")
        download = self._download(response)
        self.assertEqual(download["Content-Disposition"], 'attachment; filename="shot.png"')
        self.assertEqual(download["Content-Type"], "image/png")

    def test_persian_original_name_survives_the_round_trip(self):
        response = self._post(b"hello", name="گزارش.txt")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["original_name"], "گزارش.txt")
        download = self._download(response)
        self.assertTrue(download["Content-Disposition"].startswith("attachment; filename*=utf-8''"))
