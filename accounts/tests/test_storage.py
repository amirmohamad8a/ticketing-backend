from django.test import SimpleTestCase

from core.storage import PresignedS3Storage

NAME = "attachments/2026/10/12/a.txt"


def _storage(**overrides):
    options = {
        "bucket_name": "ticketing",
        "access_key": "test-access-key",
        "secret_key": "test-secret-key",
        "endpoint_url": "http://minio:9000",
        "region_name": "us-east-1",
        "signature_version": "s3v4",
        "addressing_style": "path",
        "default_acl": None,
        "querystring_auth": True,
        "file_overwrite": False,
    }
    options.update(overrides)
    return PresignedS3Storage(**options)


class PresignedS3StorageTests(SimpleTestCase):
    def test_url_uses_the_public_endpoint_when_one_is_configured(self):
        storage = _storage(public_endpoint_url="http://localhost:9000")
        url = storage.url(NAME, expire=60)
        self.assertTrue(url.startswith(f"http://localhost:9000/ticketing/{NAME}?"))
        self.assertIn("X-Amz-Signature=", url)
        self.assertIn("X-Amz-Expires=60", url)

    def test_url_falls_back_to_the_server_endpoint(self):
        storage = _storage()
        url = storage.url(NAME, expire=60)
        self.assertTrue(url.startswith(f"http://minio:9000/ticketing/{NAME}?"))
        self.assertIn("X-Amz-Signature=", url)
        self.assertIn("X-Amz-Expires=60", url)

    def test_default_lifetime_comes_from_the_storage_settings(self):
        storage = _storage(public_endpoint_url="http://localhost:9000", querystring_expire=90)
        self.assertIn("X-Amz-Expires=90", storage.url(NAME))

    def test_signatures_depend_on_the_file_name(self):
        storage = _storage(public_endpoint_url="http://localhost:9000")
        first = storage.url("attachments/a.txt", expire=60)
        second = storage.url("attachments/b.txt", expire=60)
        self.assertNotEqual(first, second)
