from unittest.mock import patch

from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from django.test import TestCase

from rest_framework.test import APIClient

from accounts.models import User


class UserModelTests(TestCase):
    def test_create_customer_user(self):
        user = User.objects.create_user(username="cust1", password="pass12345")
        self.assertEqual(user.role, User.Role.CUSTOMER)

    def test_create_agent_user(self):
        user = User.objects.create_user(
            username="agent1", password="pass12345", role=User.Role.AGENT
        )
        self.assertEqual(user.role, User.Role.AGENT)

    def test_create_admin_role_user(self):
        user = User.objects.create_user(
            username="admin1", password="pass12345", role=User.Role.ADMIN
        )
        self.assertEqual(user.role, User.Role.ADMIN)

    def test_create_superuser(self):
        user = User.objects.create_superuser(username="root", password="pass12345")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertEqual(user.role, User.Role.ADMIN)

    def test_create_superuser_respects_explicit_role(self):
        user = User.objects.create_superuser(
            username="root2", password="pass12345", role=User.Role.AGENT
        )
        self.assertEqual(user.role, User.Role.AGENT)

    def test_createsuperuser_command_produces_api_admin(self):
        call_command(
            "createsuperuser",
            interactive=False,
            username="cli-root",
            email="root@example.com",
            verbosity=0,
        )
        user = User.objects.get(username="cli-root")
        user.set_password("pass12345")
        user.save()
        self.assertEqual(user.role, User.Role.ADMIN)

        client = APIClient()
        token = client.post(
            "/api/token/", {"username": "cli-root", "password": "pass12345"}, format="json"
        ).json()["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(client.get("/api/users/").status_code, 200)

    def test_default_role_is_customer(self):
        user = User.objects.create_user(username="noRole", password="pass12345")
        self.assertEqual(user.role, User.Role.CUSTOMER)

    def test_str_returns_username(self):
        user = User.objects.create_user(username="strtest", password="pass12345")
        self.assertEqual(str(user), "strtest")

    def test_invalid_role_fails_full_clean(self):
        user = User(username="badrole", role="not-a-role")
        with self.assertRaises(DjangoValidationError):
            user.full_clean()


class UserAdminRegistrationTests(TestCase):
    def test_user_model_registered_in_admin(self):
        self.assertIn(User, site._registry)

    def test_admin_list_display_includes_role(self):
        admin_instance = site._registry[User]
        self.assertIn("role", admin_instance.list_display)


class TokenAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="tokenuser", password="pass12345")

    def test_obtain_token_pair(self):
        response = self.client.post(
            "/api/token/", {"username": "tokenuser", "password": "pass12345"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_obtain_token_pair_invalid_credentials(self):
        response = self.client.post("/api/token/", {"username": "tokenuser", "password": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_refresh_token_rotates_and_blacklists_old(self):
        obtain = self.client.post("/api/token/", {"username": "tokenuser", "password": "pass12345"})
        old_refresh = obtain.data["refresh"]

        refresh_response = self.client.post("/api/token/refresh/", {"refresh": old_refresh})
        self.assertEqual(refresh_response.status_code, 200)
        self.assertIn("access", refresh_response.data)
        self.assertIn("refresh", refresh_response.data)
        self.assertNotEqual(old_refresh, refresh_response.data["refresh"])

        reuse_response = self.client.post("/api/token/refresh/", {"refresh": old_refresh})
        self.assertEqual(reuse_response.status_code, 401)

    def test_logout_blacklists_refresh_token(self):
        obtain = self.client.post("/api/token/", {"username": "tokenuser", "password": "pass12345"})
        access = obtain.data["access"]
        refresh = obtain.data["refresh"]

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        logout_response = self.client.post("/api/auth/logout/", {"refresh": refresh})
        self.assertEqual(logout_response.status_code, 205)

        reuse_response = self.client.post("/api/token/refresh/", {"refresh": refresh})
        self.assertEqual(reuse_response.status_code, 401)

    def test_logout_requires_authentication(self):
        self.client.credentials()
        response = self.client.post("/api/auth/logout/", {"refresh": "sometoken"})
        self.assertEqual(response.status_code, 401)

    def test_logout_missing_refresh_token(self):
        obtain = self.client.post("/api/token/", {"username": "tokenuser", "password": "pass12345"})
        access = obtain.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = self.client.post("/api/auth/logout/", {})
        self.assertEqual(response.status_code, 400)
        self.assertIn("refresh", response.data["error"]["details"])

    def test_logout_with_a_json_array_body_is_a_validation_error(self):
        obtain = self.client.post("/api/token/", {"username": "tokenuser", "password": "pass12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {obtain.data['access']}")
        response = self.client.post("/api/auth/logout/", [obtain.data["refresh"]], format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")

    def test_logout_with_a_json_string_body_is_a_validation_error(self):
        obtain = self.client.post("/api/token/", {"username": "tokenuser", "password": "pass12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {obtain.data['access']}")
        response = self.client.post("/api/auth/logout/", obtain.data["refresh"], format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")

    def test_logout_with_a_non_string_refresh_value_is_a_validation_error(self):
        obtain = self.client.post("/api/token/", {"username": "tokenuser", "password": "pass12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {obtain.data['access']}")
        response = self.client.post(
            "/api/auth/logout/", {"refresh": {"token": obtain.data["refresh"]}}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("refresh", response.data["error"]["details"])

    def test_logout_with_a_list_refresh_value_is_a_validation_error(self):
        obtain = self.client.post("/api/token/", {"username": "tokenuser", "password": "pass12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {obtain.data['access']}")
        response = self.client.post(
            "/api/auth/logout/", {"refresh": [obtain.data["refresh"]]}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("refresh", response.data["error"]["details"])

    def test_logout_closes_the_users_live_sockets(self):
        obtain = self.client.post("/api/token/", {"username": "tokenuser", "password": "pass12345"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {obtain.data['access']}")
        with patch("accounts.views.close_user_sockets") as close_sockets:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    "/api/auth/logout/", {"refresh": obtain.data["refresh"]}
                )
        self.assertEqual(response.status_code, 205)
        close_sockets.assert_called_once_with(self.user.pk)
