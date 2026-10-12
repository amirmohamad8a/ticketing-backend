from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from core.tests.factories import AdminFactory, AgentFactory, UserFactory

URL = "/api/auth/me/"
PROFILE_KEYS = {"id", "username", "first_name", "last_name", "phone", "avatar", "role"}


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class ProfileReadTests(TestCase):
    def test_unauthenticated_requests_are_rejected(self):
        client = APIClient()
        self.assertEqual(client.get(URL).status_code, 401)
        response = client.patch(URL, {"first_name": "Sara"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "not_authenticated")

    def test_user_reads_their_own_profile(self):
        user = UserFactory(first_name="Sara", last_name="Ahmadi", phone="09123456789")
        response = _client_for(user).get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "id": user.id,
                "username": user.username,
                "first_name": "Sara",
                "last_name": "Ahmadi",
                "phone": "09123456789",
                "avatar": None,
                "role": User.Role.CUSTOMER,
            },
        )

    def test_every_role_sees_only_their_own_profile_and_no_sensitive_fields(self):
        for user in (UserFactory(), AgentFactory(), AdminFactory()):
            with self.subTest(role=user.role):
                response = _client_for(user).get(URL)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(response.data), PROFILE_KEYS)
                self.assertEqual(response.data["id"], user.id)
                self.assertEqual(response.data["role"], user.role)


class ProfileUpdateTests(TestCase):
    def setUp(self):
        self.user = UserFactory(first_name="Sara", last_name="Ahmadi", phone="09123456789")
        self.client = _client_for(self.user)

    def _patch(self, payload):
        return self.client.patch(URL, payload, format="json")

    def _stored(self):
        return User.objects.get(pk=self.user.pk)

    def test_name_and_phone_can_be_updated(self):
        response = self._patch(
            {"first_name": "Mina", "last_name": "Rezaei", "phone": "09351112233"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["first_name"], "Mina")
        self.assertEqual(response.data["phone"], "09351112233")
        stored = self._stored()
        self.assertEqual(
            (stored.first_name, stored.last_name, stored.phone),
            ("Mina", "Rezaei", "09351112233"),
        )

    def test_partial_update_changes_only_the_sent_fields(self):
        response = self._patch({"first_name": "Mina"})
        self.assertEqual(response.status_code, 200)
        stored = self._stored()
        self.assertEqual(stored.first_name, "Mina")
        self.assertEqual(stored.last_name, "Ahmadi")
        self.assertEqual(stored.phone, "09123456789")

    def test_empty_patch_changes_nothing(self):
        response = self._patch({})
        self.assertEqual(response.status_code, 200)
        stored = self._stored()
        self.assertEqual(
            (stored.first_name, stored.last_name, stored.phone),
            ("Sara", "Ahmadi", "09123456789"),
        )

    def test_persian_names_are_accepted(self):
        response = self._patch({"first_name": "علی", "last_name": "رضایی"})
        self.assertEqual(response.status_code, 200)
        stored = self._stored()
        self.assertEqual((stored.first_name, stored.last_name), ("علی", "رضایی"))

    def test_names_can_be_blanked(self):
        response = self._patch({"first_name": "", "last_name": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._stored().first_name, "")

    def test_overlong_names_are_rejected(self):
        response = self._patch({"first_name": "a" * 151})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("first_name", response.data["error"]["details"])
        self.assertEqual(self._stored().first_name, "Sara")

    def test_phone_is_normalized(self):
        for raw in ("+98 935 111 2233", "۰۹۳۵۱۱۱۲۲۳۳", "0935-111-2233"):
            with self.subTest(raw=raw):
                response = self._patch({"phone": raw})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["phone"], "09351112233")
                self.assertEqual(self._stored().phone, "09351112233")

    def test_phone_can_be_cleared(self):
        for empty in ("", None, "   "):
            with self.subTest(empty=empty):
                User.objects.filter(pk=self.user.pk).update(phone="09123456789")
                response = self._patch({"phone": empty})
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.data["phone"])
                self.assertIsNone(self._stored().phone)

    def test_invalid_phone_numbers_are_rejected(self):
        for phone in ("12345", "08123456789", "0912345678", "+982112345678", "abcdefghijk"):
            with self.subTest(phone=phone):
                response = self._patch({"phone": phone})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["error"]["code"], "validation_error")
                self.assertIn("phone", response.data["error"]["details"])
                self.assertEqual(self._stored().phone, "09123456789")

    def test_phone_used_by_someone_else_is_rejected_in_every_format(self):
        UserFactory(phone="09351112233")
        for phone in ("09351112233", "+989351112233", "۰۹۳۵۱۱۱۲۲۳۳"):
            with self.subTest(phone=phone):
                response = self._patch({"phone": phone})
                self.assertEqual(response.status_code, 400)
                self.assertIn("phone", response.data["error"]["details"])
                self.assertEqual(self._stored().phone, "09123456789")

    def test_resending_your_own_phone_is_accepted(self):
        for phone in ("09123456789", "+989123456789"):
            with self.subTest(phone=phone):
                response = self._patch({"phone": phone})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self._stored().phone, "09123456789")

    def test_read_only_and_unknown_fields_are_ignored(self):
        before = self._stored()
        response = self._patch(
            {
                "id": 999999,
                "username": "hacker",
                "role": "admin",
                "is_staff": True,
                "is_superuser": True,
                "is_active": False,
                "email": "someone@example.com",
                "password": "overwritten-1",
            }
        )
        self.assertEqual(response.status_code, 200)
        stored = self._stored()
        self.assertEqual(stored.id, before.id)
        self.assertEqual(stored.username, before.username)
        self.assertEqual(stored.role, User.Role.CUSTOMER)
        self.assertFalse(stored.is_staff)
        self.assertFalse(stored.is_superuser)
        self.assertTrue(stored.is_active)
        self.assertEqual(stored.email, before.email)
        self.assertTrue(stored.check_password("pass12345"))

    def test_put_is_not_allowed(self):
        response = self.client.put(URL, {"first_name": "Mina"}, format="json")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.data["error"]["code"], "method_not_allowed")

    def test_agents_and_admins_can_update_their_own_profile_but_keep_their_role(self):
        for factory in (AgentFactory, AdminFactory):
            user = factory()
            with self.subTest(role=user.role):
                response = _client_for(user).patch(
                    URL, {"first_name": "Staff", "role": "customer"}, format="json"
                )
                self.assertEqual(response.status_code, 200)
                user.refresh_from_db()
                self.assertEqual(user.first_name, "Staff")
                self.assertEqual(user.role, factory().role)
