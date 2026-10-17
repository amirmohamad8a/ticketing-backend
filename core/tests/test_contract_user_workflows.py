from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.admin.sites import site
from django.core.cache import cache
from django.test import Client, TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User, UserEvent
from core.tests.factories import AdminFactory, AgentFactory, TicketFactory

OLD_PASSWORD = "pass12345"
NEW_PASSWORD = "Reset-pass-6074"
ENTRYPOINTS = ("api", "admin")


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _login_refresh(user, password=OLD_PASSWORD):
    response = APIClient().post("/api/token/", {"username": user.username, "password": password})
    assert response.status_code == 200, response.data
    return response.data["refresh"]


def _token_is_valid(refresh):
    try:
        RefreshToken(refresh)
    except TokenError:
        return False
    return True


def _event_tuples(user):
    return list(
        UserEvent.objects.filter(user=user)
        .order_by("id")
        .values_list("field_changed", "old_value", "new_value", "actor_id")
    )


class UserWorkflowContractTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.admin = AdminFactory(is_staff=True, is_superuser=True)
        self.admin_api = _client_for(self.admin)
        self.admin_site = Client()
        self.admin_site.force_login(self.admin)
        self.admin_instance = site._registry[User]

    def _perform(self, entrypoint, target, payload):
        if entrypoint == "api":
            return self.admin_api.patch(f"/api/users/{target.id}/", payload, format="json")
        if "password" in payload:
            url = f"/admin/accounts/user/{target.id}/password/"
            return self.admin_site.post(
                url,
                {"password1": payload["password"], "password2": payload["password"]},
            )
        request = SimpleNamespace(user=self.admin)
        for field, value in payload.items():
            setattr(target, field, value)
        self.admin_instance.save_model(request, target, None, True)
        return None

    def _close_socket_path(self, entrypoint):
        if entrypoint == "api":
            return "accounts.serializers.close_user_sockets"
        return "accounts.admin.close_user_sockets"

    def _tickets_for(self, target):
        portal = TicketFactory(assignee=target)
        chat = TicketFactory(from_visitor=True, assignee=target)
        return portal, chat

    def test_role_change_to_customer_writes_the_same_audit_and_side_effects(self):
        for entrypoint in ENTRYPOINTS:
            with self.subTest(entrypoint=entrypoint):
                target = AgentFactory()
                refresh = _login_refresh(target)
                portal, chat = self._tickets_for(target)

                blacklisted_before = BlacklistedToken.objects.count()
                with patch(self._close_socket_path(entrypoint)) as close_sockets:
                    response = self._perform(entrypoint, target, {"role": User.Role.CUSTOMER})
                self.assertIn(getattr(response, "status_code", 200), (200, 302))

                self.assertEqual(
                    _event_tuples(target),
                    [("role", User.Role.AGENT, User.Role.CUSTOMER, self.admin.id)],
                )
                self.assertTrue(_token_is_valid(refresh))
                self.assertEqual(BlacklistedToken.objects.count(), blacklisted_before)
                portal.refresh_from_db()
                chat.refresh_from_db()
                self.assertIsNone(portal.assignee)
                self.assertIsNone(chat.assignee)
                close_sockets.assert_called_once_with(target.pk)

    def test_deactivation_writes_the_same_audit_and_side_effects(self):
        for entrypoint in ENTRYPOINTS:
            with self.subTest(entrypoint=entrypoint):
                target = AgentFactory()
                refresh = _login_refresh(target)
                portal, chat = self._tickets_for(target)

                blacklisted_before = BlacklistedToken.objects.count()
                with patch(self._close_socket_path(entrypoint)) as close_sockets:
                    response = self._perform(entrypoint, target, {"is_active": False})
                self.assertIn(getattr(response, "status_code", 200), (200, 302))

                self.assertEqual(
                    _event_tuples(target),
                    [("is_active", "true", "false", self.admin.id)],
                )
                self.assertFalse(_token_is_valid(refresh))
                self.assertEqual(BlacklistedToken.objects.count(), blacklisted_before + 1)
                portal.refresh_from_db()
                chat.refresh_from_db()
                self.assertIsNone(portal.assignee)
                self.assertIsNone(chat.assignee)
                close_sockets.assert_called_once_with(target.pk)

    def test_reactivation_writes_the_same_audit_and_side_effects(self):
        for entrypoint in ENTRYPOINTS:
            with self.subTest(entrypoint=entrypoint):
                target = AgentFactory(is_active=False)
                refresh = RefreshToken.for_user(target)
                portal = TicketFactory(assignee=target)

                blacklisted_before = BlacklistedToken.objects.count()
                with patch(self._close_socket_path(entrypoint)) as close_sockets:
                    response = self._perform(entrypoint, target, {"is_active": True})
                self.assertIn(getattr(response, "status_code", 200), (200, 302))

                self.assertEqual(
                    _event_tuples(target),
                    [("is_active", "false", "true", self.admin.id)],
                )
                self.assertTrue(_token_is_valid(str(refresh)))
                self.assertEqual(BlacklistedToken.objects.count(), blacklisted_before)
                portal.refresh_from_db()
                self.assertEqual(portal.assignee, target)
                close_sockets.assert_called_once_with(target.pk)

    def test_password_reset_writes_the_same_audit_and_side_effects(self):
        for entrypoint in ENTRYPOINTS:
            with self.subTest(entrypoint=entrypoint):
                target = AgentFactory()
                refresh = _login_refresh(target)
                portal = TicketFactory(assignee=target)

                blacklisted_before = BlacklistedToken.objects.count()
                with patch(self._close_socket_path(entrypoint)) as close_sockets:
                    response = self._perform(entrypoint, target, {"password": NEW_PASSWORD})
                self.assertIn(getattr(response, "status_code", 200), (200, 302))

                self.assertEqual(
                    _event_tuples(target),
                    [("password", "", "", self.admin.id)],
                )
                self.assertFalse(_token_is_valid(refresh))
                self.assertEqual(BlacklistedToken.objects.count(), blacklisted_before + 1)
                target.refresh_from_db()
                self.assertTrue(target.check_password(NEW_PASSWORD))
                portal.refresh_from_db()
                self.assertEqual(portal.assignee, target)
                close_sockets.assert_called_once_with(target.pk)
