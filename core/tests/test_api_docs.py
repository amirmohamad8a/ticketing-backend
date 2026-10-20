from django.conf import settings
from django.test import SimpleTestCase, TestCase

from rest_framework.test import APIClient


class DocsAssetTests(SimpleTestCase):
    def test_the_sidecar_app_is_installed(self):
        self.assertIn("drf_spectacular_sidecar", settings.INSTALLED_APPS)

    def test_swagger_ui_redoc_and_favicon_are_served_from_the_sidecar(self):
        for key in ("SWAGGER_UI_DIST", "SWAGGER_UI_FAVICON_HREF", "REDOC_DIST"):
            with self.subTest(key=key):
                self.assertEqual(settings.SPECTACULAR_SETTINGS[key], "SIDECAR")


class DocsPageTests(TestCase):
    def test_the_swagger_page_loads_no_asset_from_a_cdn(self):
        response = APIClient().get("/api/docs/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("cdn.jsdelivr.net", response.content.decode())
        self.assertIn("drf_spectacular_sidecar", response.content.decode())

    def test_the_schema_is_served_when_docs_are_enabled(self):
        self.assertTrue(settings.API_DOCS_ENABLED)
        response = APIClient().get("/api/schema/?format=json")
        self.assertEqual(response.status_code, 200)
