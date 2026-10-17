import importlib.util
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "healthcheck.py"
_spec = importlib.util.spec_from_file_location("container_healthcheck", SCRIPT_PATH)
healthcheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(healthcheck)


class HealthCheckTests(TestCase):
    def test_admin_url_resolves(self):
        response = self.client.get("/admin/")
        self.assertIn(response.status_code, (200, 302))

    def test_health_returns_ok_without_authentication(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_runs_zero_queries(self):
        with self.assertNumQueries(0):
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)

    def test_health_accepts_head_requests(self):
        with self.assertNumQueries(0):
            response = self.client.head("/health/")
        self.assertEqual(response.status_code, 200)

    def test_health_rejects_other_methods(self):
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)("/health/")
                self.assertEqual(response.status_code, 405)

    def test_health_is_not_cacheable(self):
        response = self.client.get("/health/")
        self.assertIn("no-cache", response.headers["Cache-Control"])
        self.assertIn("no-store", response.headers["Cache-Control"])


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ContainerHealthcheckTests(SimpleTestCase):
    def test_the_host_header_is_the_first_allowed_host(self):
        with patch.dict("os.environ", {"ALLOWED_HOSTS": "support.example.com,web"}):
            self.assertEqual(healthcheck._host_header(), "support.example.com")

    def test_the_host_header_falls_back_to_localhost(self):
        with patch.dict("os.environ", {"ALLOWED_HOSTS": "  ,  "}):
            self.assertEqual(healthcheck._host_header(), "localhost")

    def test_a_healthy_app_exits_zero(self):
        with patch("urllib.request.urlopen", return_value=_FakeResponse()):
            self.assertEqual(healthcheck.main(), 0)

    def test_an_unreachable_app_exits_nonzero(self):
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            self.assertEqual(healthcheck.main(), 1)

    def test_a_non_200_status_exits_nonzero(self):
        response = _FakeResponse()
        response.status = 503
        with patch("urllib.request.urlopen", return_value=response):
            self.assertEqual(healthcheck.main(), 1)
