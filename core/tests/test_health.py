import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def _connection(status=200, error=None):
    connection = MagicMock()
    if error is not None:
        connection.request.side_effect = error
    else:
        connection.getresponse.return_value.status = status
    return connection


class ContainerHealthcheckTests(SimpleTestCase):
    def test_the_host_header_is_the_first_allowed_host(self):
        with patch.dict("os.environ", {"ALLOWED_HOSTS": "support.example.com,web"}):
            self.assertEqual(healthcheck._host_header(), "support.example.com")

    def test_the_host_header_falls_back_to_localhost(self):
        with patch.dict("os.environ", {"ALLOWED_HOSTS": "  ,  "}):
            self.assertEqual(healthcheck._host_header(), "localhost")

    def test_a_healthy_app_exits_zero(self):
        with patch("http.client.HTTPConnection", return_value=_connection(200)):
            self.assertEqual(healthcheck.main(), 0)

    def test_an_unreachable_app_exits_nonzero(self):
        connection = _connection(error=OSError("refused"))
        with patch("http.client.HTTPConnection", return_value=connection):
            self.assertEqual(healthcheck.main(), 1)

    def test_a_non_200_status_exits_nonzero(self):
        with patch("http.client.HTTPConnection", return_value=_connection(503)):
            self.assertEqual(healthcheck.main(), 1)

    def test_the_probe_targets_loopback_with_the_allowed_host_header(self):
        connection = _connection(200)
        environment = {"PORT": "9000", "ALLOWED_HOSTS": "support.example.com"}
        with patch.dict("os.environ", environment):
            with patch("http.client.HTTPConnection", return_value=connection) as factory:
                healthcheck.main()
        factory.assert_called_once_with(
            "127.0.0.1", 9000, timeout=healthcheck.REQUEST_TIMEOUT_SECONDS
        )
        connection.request.assert_called_once_with(
            "GET", "/health/", headers={"Host": "support.example.com"}
        )

    def test_the_connection_is_closed_after_success_and_failure(self):
        for connection in (_connection(200), _connection(error=OSError("refused"))):
            with self.subTest(connection=connection):
                with patch("http.client.HTTPConnection", return_value=connection):
                    healthcheck.main()
                connection.close.assert_called_once_with()
