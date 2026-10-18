from django.conf import settings
from django.test import SimpleTestCase, TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken

from core.authentication import LoggedJWTAuthentication
from core.tests.factories import UserFactory


class LoggedJWTAuthenticationTests(SimpleTestCase):
    def test_it_is_the_default_authentication_class(self):
        classes = settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]
        self.assertEqual(classes, ("core.authentication.LoggedJWTAuthentication",))

    def test_it_extends_the_stock_jwt_authentication(self):
        self.assertTrue(issubclass(LoggedJWTAuthentication, JWTAuthentication))


class AuthenticationBehaviourTests(TestCase):
    def test_a_valid_access_token_still_authenticates(self):
        user = UserFactory()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        response = client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], user.id)

    def test_a_missing_or_invalid_token_is_still_rejected(self):
        self.assertEqual(APIClient().get("/api/auth/me/").status_code, 401)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer garbage")
        self.assertEqual(client.get("/api/auth/me/").status_code, 401)

    def test_the_schema_still_declares_the_jwt_security_scheme(self):
        response = APIClient().get("/api/schema/?format=json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("jwtAuth", response.json()["components"]["securitySchemes"])
