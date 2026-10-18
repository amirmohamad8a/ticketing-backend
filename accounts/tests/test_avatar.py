import io
import shutil
import tempfile
from unittest.mock import patch

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from core.tests.factories import UserFactory

URL = "/api/auth/me/"
TEST_MEDIA_ROOT = tempfile.mkdtemp()


def _image(name="avatar.png", image_format="PNG", content_type="image/png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, image_format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class AvatarTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def _upload(self, file):
        return self.client.patch(URL, {"avatar": file})

    def _avatar_name(self):
        self.user.refresh_from_db()
        return self.user.avatar.name if self.user.avatar else ""

    def _assert_rejected(self, response):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("avatar", response.data["error"]["details"])

    def test_png_upload_sets_the_avatar_and_returns_its_download_url(self):
        response = self._upload(_image())
        self.assertEqual(response.status_code, 200)
        expected = f"http://testserver/api/avatars/{self.user.id}/download/"
        self.assertEqual(response.data["avatar_download_url"], expected)
        self.assertNotIn("avatar", response.data)
        name = self._avatar_name()
        self.assertTrue(default_storage.exists(name))
        self.assertEqual(self.client.get(URL).data["avatar_download_url"], expected)

    def test_jpeg_upload_is_accepted(self):
        response = self._upload(_image("photo.JPG", "JPEG", "image/jpeg"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._avatar_name().endswith(".jpg"))

    def test_stored_name_is_random_and_ignores_the_uploaded_name(self):
        self._upload(_image(name="my photo.PNG"))
        name = self._avatar_name()
        self.assertTrue(name.startswith("avatars/"))
        self.assertNotIn("my photo", name)
        self.assertEqual(len(name), len("avatars/") + 32 + len(".png"))

    def test_extension_follows_the_real_content_not_the_uploaded_name(self):
        response = self._upload(_image(name="fake.jpg"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._avatar_name().endswith(".png"))

    def test_gif_is_rejected(self):
        response = self._upload(_image("anim.gif", "GIF", "image/gif"))
        self._assert_rejected(response)
        self.assertEqual(self._avatar_name(), "")

    def test_file_that_is_not_an_image_is_rejected(self):
        fake = SimpleUploadedFile("avatar.png", b"not an image", content_type="image/png")
        self._assert_rejected(self._upload(fake))
        self.assertEqual(self._avatar_name(), "")

    def test_file_without_an_image_extension_is_rejected(self):
        self._assert_rejected(self._upload(_image(name="avatar")))
        self.assertEqual(self._avatar_name(), "")

    def test_oversized_image_is_rejected(self):
        image = _image()
        with patch.object(User, "AVATAR_MAX_SIZE_BYTES", image.size - 1):
            self._assert_rejected(self._upload(image))
        self.assertEqual(self._avatar_name(), "")

    def test_image_at_the_exact_size_limit_is_accepted(self):
        image = _image()
        with patch.object(User, "AVATAR_MAX_SIZE_BYTES", image.size):
            response = self._upload(image)
        self.assertEqual(response.status_code, 200)

    def test_replacing_the_avatar_deletes_the_old_file(self):
        self._upload(_image())
        old_name = self._avatar_name()
        self._upload(_image(name="second.png"))
        new_name = self._avatar_name()
        self.assertNotEqual(old_name, new_name)
        self.assertFalse(default_storage.exists(old_name))
        self.assertTrue(default_storage.exists(new_name))

    def test_rejected_upload_keeps_the_current_avatar(self):
        self._upload(_image())
        old_name = self._avatar_name()
        self._assert_rejected(self._upload(_image("anim.gif", "GIF", "image/gif")))
        self.assertEqual(self._avatar_name(), old_name)
        self.assertTrue(default_storage.exists(old_name))

    def test_updating_other_fields_keeps_the_avatar_file(self):
        self._upload(_image())
        name = self._avatar_name()
        response = self.client.patch(URL, {"first_name": "Mina"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._avatar_name(), name)
        self.assertTrue(default_storage.exists(name))

    def test_avatar_can_be_cleared_with_an_empty_value(self):
        self._upload(_image())
        old_name = self._avatar_name()
        response = self.client.patch(URL, {"avatar": ""})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["avatar_download_url"])
        self.assertEqual(self._avatar_name(), "")
        self.assertFalse(default_storage.exists(old_name))

    def test_avatar_can_be_cleared_with_json_null(self):
        self._upload(_image())
        old_name = self._avatar_name()
        response = self.client.patch(URL, {"avatar": None}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["avatar_download_url"])
        self.assertFalse(default_storage.exists(old_name))

    def test_clearing_when_there_is_no_avatar_is_harmless(self):
        response = self.client.patch(URL, {"avatar": None}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["avatar_download_url"])
