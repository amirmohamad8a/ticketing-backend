from django.test import TestCase


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
