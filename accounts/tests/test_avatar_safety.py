import io
import shutil
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests import read_streaming_body
from core.tests.factories import UserFactory

URL = "/api/auth/me/"
TEST_MEDIA_ROOT = tempfile.mkdtemp()


def _image(name="avatar.png", image_format="PNG", content_type="image/png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, image_format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AvatarContentVerificationTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_avatar_that_fails_the_magic_byte_check_is_rejected(self):
        with patch("core.uploads.detect_content_type", return_value="application/pdf"):
            response = self.client.patch(URL, {"avatar": _image()})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("avatar", response.data["error"]["details"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)

    def test_genuine_images_pass_the_magic_byte_check(self):
        samples = [
            ("photo.png", "PNG", "image/png"),
            ("photo.jpg", "JPEG", "image/jpeg"),
            ("photo.webp", "WEBP", "image/webp"),
        ]
        for name, image_format, content_type in samples:
            with self.subTest(content_type=content_type):
                response = self.client.patch(
                    URL, {"avatar": _image(name, image_format, content_type)}
                )
                self.assertEqual(response.status_code, 200)

    def test_avatar_download_is_forced_and_never_sniffed(self):
        self.client.patch(URL, {"avatar": _image()})
        link = self.client.get(f"/api/avatars/{self.user.id}/download/")
        self.assertEqual(link.status_code, 200)
        response = APIClient().get(link.data["url"])
        self.assertEqual(response.status_code, 200)
        self.assertRegex(
            response["Content-Disposition"], r'^attachment; filename="[0-9a-f]{32}\.png"$'
        )
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        read_streaming_body(response)
