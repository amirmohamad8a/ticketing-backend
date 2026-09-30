from django.test import TestCase, override_settings

ALLOWED_ORIGIN = "https://frontend.example.com"


@override_settings(CORS_ALLOWED_ORIGINS=[ALLOWED_ORIGIN])
class CorsTests(TestCase):
    def _preflight(self, origin):
        return self.client.options(
            "/api/tickets/",
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )

    def test_allowed_origin_receives_cors_header(self):
        response = self._preflight(ALLOWED_ORIGIN)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], ALLOWED_ORIGIN)

    def test_unknown_origin_receives_no_cors_header(self):
        response = self._preflight("https://evil.example.com")
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_authorization_header_is_allowed(self):
        response = self._preflight(ALLOWED_ORIGIN)
        self.assertIn("authorization", response.headers["Access-Control-Allow-Headers"])
