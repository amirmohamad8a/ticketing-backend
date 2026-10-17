import os
import shutil
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock

from django.conf import settings
from django.core import signing
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from rest_framework.test import APIClient

from core.downloads import DOWNLOAD_SALT, build_download_link
from core.tests import read_streaming_body

TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SignedDownloadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.name = default_storage.save("downloads/sample.txt", ContentFile(b"hello world"))
        self.file = SimpleNamespace(name=self.name, storage=default_storage)

    def _link(self, content_type="text/plain", filename=None):
        return build_download_link(RequestFactory().get("/"), self.file, content_type, filename)

    def _token_url(self, **payload):
        data = {"name": self.name, "content_type": "text/plain", **payload}
        return f"/api/downloads/{signing.dumps(data, salt=DOWNLOAD_SALT)}/"

    def test_link_holds_a_url_and_the_configured_lifetime(self):
        link = self._link()
        self.assertEqual(set(link), {"url", "expires_in"})
        self.assertEqual(link["expires_in"], settings.DOWNLOAD_URL_TTL_SECONDS)
        self.assertTrue(link["url"].startswith("http://testserver/api/downloads/"))

    def test_link_streams_the_file_with_the_signed_content_type(self):
        response = APIClient().get(self._link()["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(read_streaming_body(response), b"hello world")
        self.assertTrue(response.is_async)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertIn("no-store", response["Cache-Control"])

    def test_response_is_forced_to_download_and_never_sniffed(self):
        response = APIClient().get(self._link()["url"])
        self.assertEqual(response.status_code, 200)
        stored_name = os.path.basename(self.name)
        self.assertEqual(response["Content-Disposition"], f'attachment; filename="{stored_name}"')
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        read_streaming_body(response)

    def test_link_carries_the_given_file_name(self):
        response = APIClient().get(self._link(filename="report 2026.txt")["url"])
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="report 2026.txt"')
        read_streaming_body(response)

    def test_links_signed_without_a_file_name_fall_back_to_the_stored_name(self):
        response = APIClient().get(self._token_url())
        stored_name = os.path.basename(self.name)
        self.assertEqual(response["Content-Disposition"], f'attachment; filename="{stored_name}"')
        read_streaming_body(response)

    def test_the_signature_is_the_only_credential_needed(self):
        url = self._link()["url"]
        response = APIClient().get(url, HTTP_AUTHORIZATION="Bearer garbage")
        self.assertEqual(response.status_code, 200)

    def test_tampered_link_is_rejected(self):
        url = self._link()["url"]
        last = url[-2]
        tampered = url[:-2] + ("A" if last != "A" else "B") + "/"
        response = APIClient().get(tampered)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "permission_denied")

    def test_link_signed_with_another_salt_is_rejected(self):
        token = signing.dumps({"name": self.name, "content_type": "text/plain"}, salt="other")
        response = APIClient().get(f"/api/downloads/{token}/")
        self.assertEqual(response.status_code, 403)

    def test_garbage_token_is_rejected(self):
        response = APIClient().get("/api/downloads/not-a-token/")
        self.assertEqual(response.status_code, 403)

    def test_expired_link_is_rejected(self):
        url = self._link()["url"]
        with override_settings(DOWNLOAD_URL_TTL_SECONDS=-1):
            response = APIClient().get(url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "permission_denied")

    def test_link_to_a_file_that_no_longer_exists_returns_404(self):
        url = self._link()["url"]
        default_storage.delete(self.name)
        response = APIClient().get(url)
        self.assertEqual(response.status_code, 404)

    def test_only_get_is_allowed(self):
        response = APIClient().post(self._token_url())
        self.assertEqual(response.status_code, 405)

    def test_media_urls_are_not_served(self):
        for path in ("/media/", f"/media/{self.name}", "/media/avatars/anything.png"):
            with self.subTest(path=path):
                self.assertEqual(APIClient().get(path).status_code, 404)


class S3DownloadLinkTests(SimpleTestCase):
    def _link(self, filename=None):
        storage = Mock()
        storage.url.return_value = "https://bucket.example/attachments/a.txt?signature=1"
        file = SimpleNamespace(name="attachments/a.txt", storage=storage)
        link = build_download_link(RequestFactory().get("/"), file, "text/plain", filename)
        return storage, link

    @override_settings(STORAGE_BACKEND="s3", DOWNLOAD_URL_TTL_SECONDS=120)
    def test_s3_backend_returns_the_presigned_url_of_the_storage(self):
        storage, link = self._link()

        self.assertEqual(
            link,
            {"url": "https://bucket.example/attachments/a.txt?signature=1", "expires_in": 120},
        )
        storage.url.assert_called_once_with(
            "attachments/a.txt",
            parameters={
                "ResponseContentType": "text/plain",
                "ResponseContentDisposition": 'attachment; filename="a.txt"',
            },
            expire=120,
        )

    @override_settings(STORAGE_BACKEND="s3", DOWNLOAD_URL_TTL_SECONDS=120)
    def test_s3_url_forces_a_download_under_the_given_file_name(self):
        storage, _ = self._link(filename="invoice.txt")

        parameters = storage.url.call_args.kwargs["parameters"]
        self.assertEqual(
            parameters["ResponseContentDisposition"], 'attachment; filename="invoice.txt"'
        )

    @override_settings(STORAGE_BACKEND="s3", DOWNLOAD_URL_TTL_SECONDS=120)
    def test_s3_url_encodes_a_persian_file_name(self):
        storage, _ = self._link(filename="گزارش.txt")

        disposition = storage.url.call_args.kwargs["parameters"]["ResponseContentDisposition"]
        self.assertTrue(disposition.startswith("attachment; filename*=utf-8''"))
        self.assertTrue(disposition.isascii())
        self.assertTrue(disposition.endswith(".txt"))
