from django.contrib.admin.sites import site
from django.test import TestCase

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
        self.assertEqual(user.role, User.Role.CUSTOMER)

    def test_default_role_is_customer(self):
        user = User.objects.create_user(username="noRole", password="pass12345")
        self.assertEqual(user.role, User.Role.CUSTOMER)

    def test_str_returns_username(self):
        user = User.objects.create_user(username="strtest", password="pass12345")
        self.assertEqual(str(user), "strtest")

    def test_invalid_role_fails_full_clean(self):
        user = User(username="badrole", role="not-a-role")
        with self.assertRaises(Exception):
            user.full_clean()


class UserAdminRegistrationTests(TestCase):
    def test_user_model_registered_in_admin(self):
        self.assertIn(User, site._registry)

    def test_admin_list_display_includes_role(self):
        admin_instance = site._registry[User]
        self.assertIn("role", admin_instance.list_display)
