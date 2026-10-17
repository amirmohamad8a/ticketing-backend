from django.db import IntegrityError, transaction
from django.test import TestCase

from rest_framework import serializers
from rest_framework.test import APIClient

from accounts.models import User
from accounts.serializers import RegisterSerializer
from core.tests.factories import UserFactory

URL = "/api/auth/register/"
PASSWORD = "S3cure-pass-91"


def _payload(**overrides):
    payload = {"username": "newuser", "password": PASSWORD}
    payload.update(overrides)
    return payload


class RegistrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _register(self, **overrides):
        return self.client.post(URL, _payload(**overrides), format="json")

    def _assert_rejected(self, response, field, expected_users=0):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])
        self.assertEqual(User.objects.count(), expected_users)

    def test_registration_creates_a_customer_and_returns_the_profile(self):
        response = self._register(first_name="Sara", last_name="Ahmadi", phone="09123456789")
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="newuser")
        self.assertEqual(
            response.data,
            {
                "id": user.id,
                "username": "newuser",
                "first_name": "Sara",
                "last_name": "Ahmadi",
                "phone": "09123456789",
                "role": User.Role.CUSTOMER,
            },
        )
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_password_is_stored_hashed(self):
        self._register()
        user = User.objects.get(username="newuser")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_registered_user_can_log_in_and_create_a_ticket(self):
        self.assertEqual(self._register().status_code, 201)
        login = self.client.post("/api/token/", {"username": "newuser", "password": PASSWORD})
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        created = self.client.post("/api/tickets/", {"title": "First ticket", "description": "d"})
        self.assertEqual(created.status_code, 201)
        user = User.objects.get(username="newuser")
        self.assertEqual(created.data["customer"], user.id)
        listing = self.client.get("/api/tickets/")
        self.assertEqual([t["id"] for t in listing.data["results"]], [created.data["id"]])

    def test_role_can_never_be_chosen(self):
        for index, role in enumerate(("admin", "agent", "customer", "superuser", "")):
            with self.subTest(role=role):
                username = f"roleuser{index}"
                response = self._register(username=username, role=role)
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data["role"], User.Role.CUSTOMER)
                self.assertEqual(User.objects.get(username=username).role, User.Role.CUSTOMER)

    def test_privileged_flags_are_ignored(self):
        response = self._register(is_staff=True, is_superuser=True, is_active=False)
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="newuser")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)

    def test_email_is_not_collected(self):
        response = self._register(email="someone@example.com")
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("email", response.data)
        self.assertEqual(User.objects.get(username="newuser").email, "")

    def test_a_garbage_authorization_header_does_not_block_registration(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        self.assertEqual(self._register().status_code, 201)

    def test_only_post_is_allowed(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.data["error"]["code"], "method_not_allowed")

    def test_names_are_optional(self):
        response = self._register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["first_name"], "")
        self.assertEqual(response.data["last_name"], "")

    def test_persian_names_and_usernames_are_accepted(self):
        response = self._register(username="علی_رضایی", first_name="علی", last_name="رضایی")
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="علی_رضایی")
        self.assertEqual((user.first_name, user.last_name), ("علی", "رضایی"))


class RegistrationPasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _register(self, **overrides):
        return self.client.post(URL, _payload(**overrides), format="json")

    def _assert_password_rejected(self, response):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("password", response.data["error"]["details"])
        self.assertFalse(User.objects.exists())

    def test_weak_passwords_are_rejected(self):
        for password in ("short1", "password", "83927461"):
            with self.subTest(password=password):
                self._assert_password_rejected(self._register(password=password))

    def test_password_similar_to_the_username_is_rejected(self):
        response = self._register(username="mohammad", password="mohammad1")
        self._assert_password_rejected(response)

    def test_blank_password_is_rejected(self):
        self._assert_password_rejected(self._register(password=""))

    def test_overlong_password_is_rejected(self):
        self._assert_password_rejected(self._register(password="a1b2c3d4" * 17))

    def test_missing_password_is_rejected(self):
        payload = {"username": "newuser"}
        response = self.client.post(URL, payload, format="json")
        self._assert_password_rejected(response)

    def test_password_is_not_trimmed(self):
        password = f" {PASSWORD} "
        self.assertEqual(self._register(password=password).status_code, 201)
        user = User.objects.get(username="newuser")
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.check_password(PASSWORD))


class RegistrationUsernameTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _register(self, **overrides):
        return self.client.post(URL, _payload(**overrides), format="json")

    def _assert_rejected(self, response, expected_users):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("username", response.data["error"]["details"])
        self.assertEqual(User.objects.count(), expected_users)

    def test_username_is_required(self):
        response = self.client.post(URL, {"password": PASSWORD}, format="json")
        self._assert_rejected(response, expected_users=0)

    def test_username_must_be_unique_ignoring_case(self):
        UserFactory(username="Taken")
        for username in ("Taken", "taken", "TAKEN"):
            with self.subTest(username=username):
                self._assert_rejected(self._register(username=username), expected_users=1)

    def test_lookalike_unicode_usernames_are_rejected(self):
        UserFactory(username="admin")
        fullwidth = "\uff41\uff44\uff4d\uff49\uff4e"
        self._assert_rejected(self._register(username=fullwidth), expected_users=1)

    def test_username_with_invalid_characters_is_rejected(self):
        self._assert_rejected(self._register(username="bad name"), expected_users=0)


class RegistrationPhoneTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _register(self, **overrides):
        return self.client.post(URL, _payload(**overrides), format="json")

    def _assert_rejected(self, response, expected_users):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("phone", response.data["error"]["details"])
        self.assertEqual(User.objects.count(), expected_users)

    def test_phone_is_optional(self):
        response = self._register()
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data["phone"])
        self.assertIsNone(User.objects.get(username="newuser").phone)

    def test_blank_and_null_phones_are_stored_as_null(self):
        for index, phone in enumerate(("", None, "   ")):
            with self.subTest(phone=phone):
                username = f"nophone{index}"
                response = self._register(username=username, phone=phone)
                self.assertEqual(response.status_code, 201)
                self.assertIsNone(User.objects.get(username=username).phone)

    def test_phone_is_normalized_before_it_is_stored(self):
        response = self._register(phone="+98 912 345 6789")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["phone"], "09123456789")
        self.assertEqual(User.objects.get(username="newuser").phone, "09123456789")

    def test_persian_digits_in_the_phone_are_accepted(self):
        response = self._register(phone="۰۹۱۲۳۴۵۶۷۸۹")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.get(username="newuser").phone, "09123456789")

    def test_invalid_phone_numbers_are_rejected(self):
        invalid = ("12345", "08123456789", "0912345678", "091234567890", "abcdefghijk")
        for phone in invalid + ("+982112345678",):
            with self.subTest(phone=phone):
                self._assert_rejected(self._register(phone=phone), expected_users=0)

    def test_phone_must_be_unique_across_formats(self):
        UserFactory(phone="09123456789")
        for phone in ("09123456789", "+989123456789", "۰۹۱۲۳۴۵۶۷۸۹"):
            with self.subTest(phone=phone):
                self._assert_rejected(self._register(phone=phone), expected_users=1)


class RegistrationUsernameRaceTests(TestCase):
    def test_the_database_rejects_case_insensitive_duplicate_usernames(self):
        User.objects.create_user(username="Ali", password=PASSWORD)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(username="ali", password=PASSWORD)

    def test_a_lowercase_collision_is_mapped_to_the_username_field_error(self):
        User.objects.create_user(username="Ali", password=PASSWORD)
        serializer = RegisterSerializer()
        with self.assertRaises(serializers.ValidationError) as caught:
            serializer.create(
                {
                    "username": "ali",
                    "password": PASSWORD,
                    "first_name": "",
                    "last_name": "",
                    "phone": None,
                }
            )
        self.assertIn("username", caught.exception.detail)
