from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import AdminFactory, UserFactory

PASSWORD = "Old-pass-4821"
NEW_PASSWORD = "New-pass-7390"
PASSWORD_CHANGE_URL = "/api/auth/password/change/"
PROTECTED_URL = "/api/tickets/"


def _login(user, password=PASSWORD):
    response = APIClient().post("/api/token/", {"username": user.username, "password": password})
    return response.data["access"], response.data["refresh"]


def _client_with_access(access):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


def _client_for(user):
    refresh = RefreshToken.for_user(user)
    return _client_with_access(str(refresh.access_token))


def _status(access):
    return _client_with_access(access).get(PROTECTED_URL).status_code


class AccessTokenRevocationTests(TestCase):
    def setUp(self):
        self.user = UserFactory(password=PASSWORD)
        self.access, self.refresh = _login(self.user)

    def _change_password(self, access=None):
        client = _client_with_access(access or self.access)
        return client.post(
            PASSWORD_CHANGE_URL,
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD},
            format="json",
        )

    def test_the_access_token_works_until_something_changes(self):
        self.assertEqual(_status(self.access), 200)

    def test_a_password_change_revokes_the_old_access_token_at_once(self):
        response = self._change_password()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_status(self.access), 401)
        self.assertEqual(_status(response.data["access"]), 200)

    def test_every_access_token_of_the_user_is_revoked(self):
        other_access, _ = _login(self.user)
        self._change_password()
        self.assertEqual(_status(other_access), 401)

    def test_an_admin_password_reset_revokes_the_access_token(self):
        response = _client_for(AdminFactory()).patch(
            f"/api/users/{self.user.id}/", {"password": NEW_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_status(self.access), 401)
        new_access, _ = _login(self.user, NEW_PASSWORD)
        self.assertEqual(_status(new_access), 200)

    def test_deactivation_revokes_the_access_token(self):
        response = _client_for(AdminFactory()).patch(
            f"/api/users/{self.user.id}/", {"is_active": False}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_status(self.access), 401)

    def test_refreshing_after_a_password_change_gives_a_working_access_token(self):
        changed = self._change_password()
        refreshed = APIClient().post("/api/token/refresh/", {"refresh": changed.data["refresh"]})
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(_status(refreshed.data["access"]), 200)

    def test_other_users_access_tokens_are_untouched(self):
        other = UserFactory(password=PASSWORD)
        other_access, _ = _login(other)
        self._change_password()
        self.assertEqual(_status(other_access), 200)
