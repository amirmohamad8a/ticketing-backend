from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import authenticate
from django.test import TestCase

from asgiref.sync import async_to_sync
from rest_framework.test import APIClient

from accounts.backends import CaseInsensitiveModelBackend
from core.tests.factories import UserFactory

PASSWORD = "pass12345"
CASINGS = ("Ali", "ali", "ALI", "aLi")


class CaseInsensitiveLoginTests(TestCase):
    def setUp(self):
        self.user = UserFactory(username="Ali", password=PASSWORD)

    def _token(self, username, password=PASSWORD):
        return APIClient().post("/api/token/", {"username": username, "password": password})

    def test_the_backend_is_registered(self):
        self.assertEqual(
            settings.AUTHENTICATION_BACKENDS,
            [
                "accounts.backends.CaseInsensitiveModelBackend",
            ],
        )

    def test_every_casing_of_the_username_can_log_in(self):
        for username in CASINGS:
            with self.subTest(username=username):
                self.assertEqual(self._token(username).status_code, 200)

    def test_a_wrong_password_is_refused_in_every_casing(self):
        for username in CASINGS:
            with self.subTest(username=username):
                self.assertEqual(self._token(username, "wrong-pass-1").status_code, 401)

    def test_authenticate_returns_the_stored_user_for_any_casing(self):
        for username in CASINGS:
            with self.subTest(username=username):
                self.assertEqual(authenticate(username=username, password=PASSWORD), self.user)

    def test_an_inactive_user_is_refused_in_every_casing(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        for username in CASINGS:
            with self.subTest(username=username):
                self.assertIsNone(authenticate(username=username, password=PASSWORD))
                self.assertEqual(self._token(username).status_code, 401)

    def test_an_unknown_user_is_refused_without_an_error(self):
        self.assertIsNone(authenticate(username="nobody", password=PASSWORD))

    def test_a_missing_user_still_runs_the_dummy_password_hash(self):
        backend = CaseInsensitiveModelBackend()
        with patch(
            "accounts.backends.check_password_with_timing_attack_mitigation", return_value=False
        ) as check:
            self.assertIsNone(backend.authenticate(None, username="nobody", password=PASSWORD))
        check.assert_called_once_with(None, PASSWORD)

    def test_the_async_path_is_case_insensitive_too(self):
        backend = CaseInsensitiveModelBackend()
        self.assertEqual(
            async_to_sync(backend.aauthenticate)(None, username="ALI", password=PASSWORD),
            self.user,
        )
        self.assertIsNone(
            async_to_sync(backend.aauthenticate)(None, username="ALI", password="wrong-pass-1")
        )
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertIsNone(
            async_to_sync(backend.aauthenticate)(None, username="ali", password=PASSWORD)
        )
