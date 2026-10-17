from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.tokens import blacklist_user_tokens
from core.tests.factories import UserFactory

URL = "/api/auth/password/change/"
OLD_PASSWORD = "Old-pass-4821"
NEW_PASSWORD = "New-pass-7390"
THIRD_PASSWORD = "Third-pass-5512"


def _login(user, password=OLD_PASSWORD):
    response = APIClient().post("/api/token/", {"username": user.username, "password": password})
    return response.data["access"], response.data["refresh"]


def _refresh_status(refresh):
    return APIClient().post("/api/token/refresh/", {"refresh": refresh}).status_code


def _refresh_token_is_valid(refresh):
    try:
        RefreshToken(refresh)
    except TokenError:
        return False
    return True


def _authenticated_client(access):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = UserFactory(password=OLD_PASSWORD)
        self.access, self.refresh = _login(self.user)
        self.client = _authenticated_client(self.access)

    def _change(self, old=OLD_PASSWORD, new=NEW_PASSWORD, client=None):
        client = client or self.client
        return client.post(URL, {"old_password": old, "new_password": new}, format="json")

    def _assert_rejected(self, response, field):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))
        self.assertTrue(_refresh_token_is_valid(self.refresh))

    def test_unauthenticated_request_is_rejected(self):
        response = self._change(client=APIClient())
        self.assertEqual(response.status_code, 401)

    def test_only_post_is_allowed(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 405)

    def test_change_updates_the_password_and_returns_a_token_pair(self):
        response = self._change()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"access", "refresh"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertFalse(self.user.check_password(OLD_PASSWORD))

    def test_login_works_with_the_new_password_only(self):
        self._change()
        client = APIClient()
        old = client.post("/api/token/", {"username": self.user.username, "password": OLD_PASSWORD})
        new = client.post("/api/token/", {"username": self.user.username, "password": NEW_PASSWORD})
        self.assertEqual(old.status_code, 401)
        self.assertEqual(new.status_code, 200)

    def test_old_refresh_token_fails_after_the_change(self):
        self._change()
        self.assertEqual(_refresh_status(self.refresh), 401)

    def test_every_other_session_is_logged_out(self):
        other_sessions = [_login(self.user)[1] for _ in range(2)]
        self._change()
        for refresh in [self.refresh, *other_sessions]:
            self.assertEqual(_refresh_status(refresh), 401)

    def test_every_outstanding_token_of_the_user_ends_up_blacklisted(self):
        _login(self.user)
        self._change()
        outstanding = OutstandingToken.objects.filter(user=self.user)
        blacklisted = BlacklistedToken.objects.filter(token__user=self.user)
        self.assertEqual(blacklisted.count(), outstanding.count() - 1)

    def test_returned_tokens_keep_the_current_session_alive(self):
        response = self._change()
        client = _authenticated_client(response.data["access"])
        self.assertEqual(client.get("/api/tickets/").status_code, 200)
        self.assertEqual(_refresh_status(response.data["refresh"]), 200)

    def test_the_change_closes_the_users_live_sockets(self):
        with patch("accounts.views.close_user_sockets") as close_sockets:
            with self.captureOnCommitCallbacks(execute=True):
                response = self._change()
        self.assertEqual(response.status_code, 200)
        close_sockets.assert_called_once_with(self.user.pk)

    def test_other_users_sessions_are_untouched(self):
        other = UserFactory(password=OLD_PASSWORD)
        _, other_refresh = _login(other)
        self._change()
        self.assertEqual(_refresh_status(other_refresh), 200)

    def test_a_second_change_revokes_the_pair_returned_by_the_first(self):
        first = self._change()
        client = _authenticated_client(first.data["access"])
        second = self._change(old=NEW_PASSWORD, new=THIRD_PASSWORD, client=client)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(_refresh_status(first.data["refresh"]), 401)
        self.assertEqual(_refresh_status(second.data["refresh"]), 200)

    def test_wrong_old_password_is_rejected(self):
        self._assert_rejected(self._change(old="Wrong-pass-0000"), "old_password")

    def test_weak_new_passwords_are_rejected(self):
        for password in ("short1", "password", "83927461"):
            with self.subTest(password=password):
                self._assert_rejected(self._change(new=password), "new_password")

    def test_new_password_similar_to_the_username_is_rejected(self):
        user = UserFactory(username="mohammad", password=OLD_PASSWORD)
        access, _ = _login(user)
        response = self._change(new="mohammad1", client=_authenticated_client(access))
        self.assertEqual(response.status_code, 400)
        self.assertIn("new_password", response.data["error"]["details"])
        user.refresh_from_db()
        self.assertTrue(user.check_password(OLD_PASSWORD))

    def test_new_password_must_differ_from_the_old_one(self):
        self._assert_rejected(self._change(new=OLD_PASSWORD), "new_password")

    def test_overlong_new_password_is_rejected(self):
        self._assert_rejected(self._change(new="a1b2c3d4" * 17), "new_password")

    def test_missing_and_blank_fields_are_rejected(self):
        payloads = [
            ({}, {"old_password", "new_password"}),
            ({"old_password": OLD_PASSWORD}, {"new_password"}),
            ({"new_password": NEW_PASSWORD}, {"old_password"}),
            ({"old_password": "", "new_password": ""}, {"old_password", "new_password"}),
        ]
        for payload, expected in payloads:
            with self.subTest(payload=payload):
                response = self.client.post(URL, payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(set(response.data["error"]["details"]), expected)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_new_password_is_not_trimmed(self):
        padded = f" {NEW_PASSWORD} "
        self.assertEqual(self._change(new=padded).status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(padded))
        self.assertFalse(self.user.check_password(NEW_PASSWORD))


class BlacklistUserTokensTests(TestCase):
    def test_blacklists_every_live_token_of_the_user_only(self):
        user = UserFactory()
        other = UserFactory()
        tokens = [RefreshToken.for_user(user) for _ in range(3)]
        other_token = RefreshToken.for_user(other)
        tokens[0].blacklist()

        self.assertEqual(blacklist_user_tokens(user), 2)

        for token in tokens:
            with self.assertRaises(TokenError):
                RefreshToken(str(token))
        RefreshToken(str(other_token))

    def test_second_call_has_nothing_left_to_do(self):
        user = UserFactory()
        RefreshToken.for_user(user)
        self.assertEqual(blacklist_user_tokens(user), 1)
        self.assertEqual(blacklist_user_tokens(user), 0)

    def test_expired_tokens_are_skipped(self):
        user = UserFactory()
        OutstandingToken.objects.create(
            user=user,
            jti="expired-jti",
            token="expired",
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertEqual(blacklist_user_tokens(user), 0)
        self.assertFalse(BlacklistedToken.objects.filter(token__jti="expired-jti").exists())

    def test_user_without_tokens_is_a_no_op(self):
        self.assertEqual(blacklist_user_tokens(UserFactory()), 0)
