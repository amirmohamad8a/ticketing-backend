from django.test import TestCase


class HealthCheckTests(TestCase):
    def test_admin_url_resolves(self):
        response = self.client.get("/admin/")
        self.assertIn(response.status_code, (200, 302))
