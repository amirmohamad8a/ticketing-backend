import io
import re
import zipfile

from django.test import TestCase

from core.tests.factories import CommentFactory, TicketFactory, UserFactory
from core.tests.security_support import (
    PDF_BYTES,
    PNG_BYTES,
    SCRIPT_BYTES,
    client_for,
    make_world,
    stored_files,
    upload,
    use_temp_media,
    visitor_client,
)
from core.uploads import DOCX_CONTENT_TYPE
from tickets.models import Attachment, Comment, Ticket

ELF_BYTES = b"\x7fELF\x02\x01\x01" + b"\x00" * 57
MZ_BYTES = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 56
SVG_BYTES = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
HTML_BYTES = b"<html><script>alert(1)</script></html>"


def _zip(*names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "content")
    return buffer.getvalue()


PLAIN_ZIP = _zip("notes.txt")
TRAVERSAL_ZIP = _zip("../../evil.sh", "/etc/cron.d/job")

REJECTED_UPLOADS = [
    ("photo.png", SCRIPT_BYTES, "image/png"),
    ("report.pdf", PNG_BYTES, "application/pdf"),
    ("report.pdf", ELF_BYTES, "application/pdf"),
    ("notes.txt", ELF_BYTES, "text/plain"),
    ("photo.png", MZ_BYTES, "image/png"),
    ("photo.jpg", PNG_BYTES, "image/jpeg"),
    ("notes.txt", PDF_BYTES, "text/plain"),
    ("logo.svg", SVG_BYTES, "image/svg+xml"),
    ("page.html", HTML_BYTES, "text/html"),
    ("run.js", b"alert(1)", "application/javascript"),
    ("blob.bin", b"\x00\x01\x02", "application/octet-stream"),
    ("letter.docx", PLAIN_ZIP, DOCX_CONTENT_TYPE),
]

STORED_NAME = re.compile(r"^attachments/\d{4}/\d{2}/\d{2}/[0-9a-f]{32}\.[a-z]+$")


class TicketUploadAbuseTests(TestCase):
    def setUp(self):
        self.media = use_temp_media(self)
        self.customer = UserFactory()
        self.ticket = TicketFactory(customer=self.customer)
        self.comment = CommentFactory(ticket=self.ticket, author=self.customer)
        self.client = client_for(self.customer)
        self.urls = [
            f"/api/tickets/{self.ticket.id}/attachments/",
            f"/api/tickets/{self.ticket.id}/comments/{self.comment.id}/attachments/",
        ]

    def test_every_disguised_or_disallowed_file_is_rejected_and_nothing_is_stored(self):
        for url in self.urls:
            for name, content, declared in REJECTED_UPLOADS:
                with self.subTest(url=url[-30:], name=name, declared=declared):
                    response = self.client.post(url, {"file": upload(content, name, declared)})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("file", response.data["error"]["details"])
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(stored_files(self.media), [])

    def test_text_that_is_not_a_file_is_rejected(self):
        for url in self.urls:
            with self.subTest(url=url[-30:]):
                response = self.client.post(url, {"file": "http://169.254.169.254/latest"})
                self.assertEqual(response.status_code, 400)
                json_response = self.client.post(url, {"file": "not-a-file"}, format="json")
                self.assertEqual(json_response.status_code, 400)
        self.assertEqual(Attachment.objects.count(), 0)

    def test_an_archive_with_traversal_paths_is_stored_unopened_under_a_random_name(self):
        response = self.client.post(
            self.urls[0], {"file": upload(TRAVERSAL_ZIP, "bundle.zip", "application/zip")}
        )
        self.assertEqual(response.status_code, 201)
        name = Attachment.objects.get().file.name
        self.assertRegex(name, STORED_NAME)
        self.assertTrue(name.endswith(".zip"))
        files = stored_files(self.media)
        self.assertEqual(len(files), 1)
        self.assertFalse(any("evil" in path or "cron" in path for path in files))

    def test_a_traversal_file_name_never_reaches_the_stored_name(self):
        response = self.client.post(
            self.urls[0], {"file": upload(b"hello", "../../etc/passwd.txt")}
        )
        self.assertEqual(response.status_code, 201)
        stored = Attachment.objects.get()
        self.assertRegex(stored.file.name, STORED_NAME)
        self.assertNotIn("passwd", stored.file.name)
        self.assertEqual(stored.original_name, "passwd.txt")

    def test_a_file_that_looks_like_a_web_page_is_served_as_a_plain_text_download(self):
        response = self.client.post(
            self.urls[0], {"file": upload(HTML_BYTES, "page.html", "text/plain")}
        )
        self.assertEqual(response.status_code, 201)
        link = self.client.get(f"/api/attachments/{response.data['id']}/download/")
        self.assertEqual(link.status_code, 200)
        download = self.client_without_login().get(link.data["url"])
        self.assertEqual(download.status_code, 200)
        b"".join(download.streaming_content)
        self.assertEqual(download["Content-Type"], "text/plain")
        self.assertTrue(download["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(download["X-Content-Type-Options"], "nosniff")

    def client_without_login(self):
        from rest_framework.test import APIClient

        return APIClient()


class AvatarUploadAbuseTests(TestCase):
    def setUp(self):
        self.media = use_temp_media(self)
        self.user = UserFactory()
        self.client = client_for(self.user)

    def test_disguised_and_disallowed_avatars_are_rejected(self):
        cases = [
            ("avatar.svg", SVG_BYTES, "image/svg+xml"),
            ("avatar.png", ELF_BYTES, "image/png"),
            ("avatar.png", HTML_BYTES, "image/png"),
            ("avatar.png", SCRIPT_BYTES, "image/png"),
            ("avatar.png", PDF_BYTES, "image/png"),
        ]
        for name, content, declared in cases:
            with self.subTest(name=name, declared=declared, size=len(content)):
                response = self.client.patch(
                    "/api/auth/me/", {"avatar": upload(content, name, declared)}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("avatar", response.data["error"]["details"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)
        self.assertEqual(stored_files(self.media), [])

    def test_an_avatar_cannot_be_a_url_or_a_path(self):
        for value in ("http://169.254.169.254/latest", "../../etc/passwd", "file:///etc/passwd"):
            with self.subTest(value=value):
                response = self.client.patch("/api/auth/me/", {"avatar": value})
                self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)


class WidgetUploadAbuseTests(TestCase):
    def setUp(self):
        self.media = use_temp_media(self)
        self.world = make_world()
        self.client = visitor_client(self.world.visitor_a)
        self.url = f"/api/widget/conversations/{self.world.ticket_a.id}/attachments/"

    def test_disguised_files_are_rejected_and_leave_no_message_behind(self):
        before = Comment.objects.count()
        for name, content, declared in REJECTED_UPLOADS:
            with self.subTest(name=name, declared=declared):
                response = self.client.post(
                    self.url, {"file": upload(content, name, declared), "body": "see"}
                )
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Comment.objects.count(), before)
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(stored_files(self.media), [])

    def test_an_oversized_file_is_rejected_and_leaves_no_message_behind(self):
        before = Comment.objects.count()
        content = b"x" * (Attachment.MAX_SIZE_BYTES + 1)
        response = self.client.post(self.url, {"file": upload(content)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Comment.objects.count(), before)
        self.assertEqual(stored_files(self.media), [])

    def test_a_closed_conversation_accepts_no_files(self):
        Ticket.objects.filter(pk=self.world.ticket_a.pk).update(status=Ticket.Status.RESOLVED)
        before = Comment.objects.count()
        response = self.client.post(self.url, {"file": upload(b"hello")})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "conversation_closed")
        self.assertEqual(Comment.objects.count(), before)
        self.assertEqual(stored_files(self.media), [])

    def test_only_multipart_uploads_are_accepted(self):
        response = self.client.post(self.url, {"file": "x"}, format="json")
        self.assertEqual(response.status_code, 415)
        self.assertEqual(Attachment.objects.count(), 0)

    def test_message_bodies_have_a_length_limit(self):
        before = Comment.objects.count()
        url = f"/api/widget/conversations/{self.world.ticket_a.id}/messages/"
        response = self.client.post(url, {"body": "x" * 4001}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("body", response.data["error"]["details"])
        self.assertEqual(Comment.objects.count(), before)
