from django.test import TestCase

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User, UserEvent
from accounts.pagination import UserCursorPagination
from core.tests.factories import AdminFactory, AgentFactory, TicketFactory, UserFactory

URL = "/api/users/"
PASSWORD = "S3cure-pass-91"
NEW_PASSWORD = "Reset-pass-6074"
PAGE_SIZE = UserCursorPagination.page_size
USER_KEYS = {
    "id",
    "username",
    "first_name",
    "last_name",
    "phone",
    "role",
    "is_active",
    "date_joined",
}

ROLES = ["unauthenticated", "customer", "agent", "admin"]
EXPECTED = {
    "list": (401, 403, 403, 200),
    "retrieve": (401, 403, 403, 200),
    "create": (401, 403, 403, 201),
    "update_role": (401, 403, 403, 200),
    "update_active": (401, 403, 403, 200),
    "reset_password": (401, 403, 403, 200),
    "put": (401, 403, 403, 405),
    "delete": (401, 403, 403, 405),
}
MATRIX = [
    (role, action, statuses[index])
    for action, statuses in EXPECTED.items()
    for index, role in enumerate(ROLES)
]


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _client_with_access(access):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


def _login(user, password="pass12345"):
    return APIClient().post("/api/token/", {"username": user.username, "password": password})


def _refresh_token_is_valid(refresh):
    try:
        RefreshToken(refresh)
    except TokenError:
        return False
    return True


@pytest.mark.django_db
@pytest.mark.parametrize("role,action,expected_status", MATRIX)
def test_user_management_permission_matrix(role, action, expected_status):
    users = {
        "customer": UserFactory(),
        "agent": AgentFactory(),
        "admin": AdminFactory(),
    }
    target = AgentFactory()
    detail_url = f"{URL}{target.id}/"

    client = APIClient()
    if role != "unauthenticated":
        refresh = RefreshToken.for_user(users[role])
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    if action == "list":
        response = client.get(URL)
    elif action == "retrieve":
        response = client.get(detail_url)
    elif action == "create":
        response = client.post(URL, {"username": "matrix_new", "password": PASSWORD}, format="json")
    elif action == "update_role":
        response = client.patch(detail_url, {"role": User.Role.CUSTOMER}, format="json")
    elif action == "update_active":
        response = client.patch(detail_url, {"is_active": False}, format="json")
    elif action == "reset_password":
        response = client.patch(detail_url, {"password": NEW_PASSWORD}, format="json")
    elif action == "put":
        response = client.put(detail_url, {"role": User.Role.ADMIN}, format="json")
    elif action == "delete":
        response = client.delete(detail_url)

    assert response.status_code == expected_status


class UserListTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)

    def _ids(self, response):
        return [user["id"] for user in response.data["results"]]

    def test_list_returns_every_user_with_the_profile_fields_only(self):
        agent = AgentFactory(first_name="Sara", phone="09123456789")
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        ids = self._ids(response)
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(set(ids), {self.admin.id, agent.id})
        row = next(item for item in response.data["results"] if item["id"] == agent.id)
        self.assertEqual(set(row), USER_KEYS)
        self.assertEqual(row["first_name"], "Sara")
        self.assertEqual(row["phone"], "09123456789")
        self.assertEqual(row["role"], User.Role.AGENT)
        self.assertTrue(row["is_active"])

    def test_inactive_users_are_listed(self):
        inactive = UserFactory(is_active=False)
        self.assertIn(inactive.id, self._ids(self.client.get(URL)))

    def test_role_filter(self):
        agent = AgentFactory()
        UserFactory()
        response = self.client.get(f"{URL}?role=agent")
        self.assertEqual(set(self._ids(response)), {agent.id})

    def test_is_active_filter(self):
        inactive = UserFactory(is_active=False)
        agent = AgentFactory()
        only_inactive = self.client.get(f"{URL}?is_active=false")
        self.assertEqual(set(self._ids(only_inactive)), {inactive.id})
        only_active = self.client.get(f"{URL}?is_active=true")
        self.assertEqual(set(self._ids(only_active)), {self.admin.id, agent.id})

    def test_filters_combine(self):
        inactive_agent = AgentFactory(is_active=False)
        AgentFactory()
        UserFactory(is_active=False)
        response = self.client.get(f"{URL}?role=agent&is_active=false")
        self.assertEqual(set(self._ids(response)), {inactive_agent.id})

    def test_invalid_role_filter_is_rejected(self):
        response = self.client.get(f"{URL}?role=bogus")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("role", response.data["error"]["details"])

    def test_list_is_paginated_with_a_cursor(self):
        UserFactory.create_batch(PAGE_SIZE + 5)
        first = self.client.get(URL)
        self.assertEqual(len(first.data["results"]), PAGE_SIZE)
        self.assertIsNotNone(first.data["next"])
        second = self.client.get(first.data["next"])
        self.assertEqual(len(second.data["results"]), 6)
        self.assertIsNone(second.data["next"])
        walked = self._ids(first) + self._ids(second)
        self.assertEqual(len(set(walked)), PAGE_SIZE + 6)


class UserRetrieveTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)

    def test_admin_can_read_any_user(self):
        for user in (UserFactory(), AgentFactory(), UserFactory(is_active=False)):
            with self.subTest(role=user.role, active=user.is_active):
                response = self.client.get(f"{URL}{user.id}/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(response.data), USER_KEYS)
                self.assertEqual(response.data["id"], user.id)

    def test_unknown_user_returns_404(self):
        response = self.client.get(f"{URL}999999/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "not_found")


class UserCreateTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)

    def _create(self, **overrides):
        payload = {"username": "newagent", "password": PASSWORD}
        payload.update(overrides)
        return self.client.post(URL, payload, format="json")

    def _assert_rejected(self, response, field):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(UserEvent.objects.exists())

    def test_user_is_created_as_an_agent_by_default(self):
        response = self._create(first_name="Sara", last_name="Ahmadi", phone="09123456789")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), USER_KEYS)
        user = User.objects.get(username="newagent")
        self.assertEqual(response.data["id"], user.id)
        self.assertEqual(response.data["role"], User.Role.AGENT)
        self.assertTrue(response.data["is_active"])
        self.assertEqual(response.data["phone"], "09123456789")
        self.assertEqual(user.role, User.Role.AGENT)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_password_is_stored_hashed_and_never_returned(self):
        response = self._create()
        self.assertNotIn("password", response.data)
        user = User.objects.get(username="newagent")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_creation_writes_an_audit_row(self):
        self._create()
        user = User.objects.get(username="newagent")
        event = UserEvent.objects.get()
        self.assertEqual(event.user, user)
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.field_changed, "created")
        self.assertEqual(event.old_value, "")
        self.assertEqual(event.new_value, User.Role.AGENT)

    def test_every_role_can_be_chosen(self):
        for index, role in enumerate(User.Role.values):
            with self.subTest(role=role):
                response = self._create(username=f"chosen{index}", role=role)
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data["role"], role)
                self.assertEqual(User.objects.get(username=f"chosen{index}").role, role)

    def test_invalid_role_is_rejected(self):
        for role in ("superuser", ""):
            with self.subTest(role=role):
                self._assert_rejected(self._create(role=role), "role")

    def test_privileged_flags_are_ignored(self):
        response = self._create(is_staff=True, is_superuser=True, is_active=False)
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="newagent")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)

    def test_created_user_can_log_in(self):
        self._create()
        response = _login(User.objects.get(username="newagent"), PASSWORD)
        self.assertEqual(response.status_code, 200)

    def test_weak_passwords_are_rejected(self):
        for password in ("short1", "password", "83927461"):
            with self.subTest(password=password):
                self._assert_rejected(self._create(password=password), "password")

    def test_password_similar_to_the_username_is_rejected(self):
        response = self._create(username="mohammad", password="mohammad1")
        self._assert_rejected(response, "password")

    def test_missing_username_and_password_are_rejected(self):
        response = self.client.post(URL, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.data["error"]["details"]), {"username", "password"})

    def test_username_must_be_unique_ignoring_case(self):
        UserFactory(username="Taken")
        response = self._create(username="taken")
        self.assertEqual(response.status_code, 400)
        self.assertIn("username", response.data["error"]["details"])
        self.assertFalse(UserEvent.objects.exists())

    def test_phone_is_normalized_and_must_be_unique(self):
        response = self._create(phone="+98 912 345 6789")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["phone"], "09123456789")
        duplicate = self._create(username="another", phone="۰۹۱۲۳۴۵۶۷۸۹")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("phone", duplicate.data["error"]["details"])
        self.assertFalse(User.objects.filter(username="another").exists())

    def test_invalid_phone_is_rejected(self):
        self._assert_rejected(self._create(phone="12345"), "phone")


class UserUpdateTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)
        self.target = AgentFactory()
        self.url = f"{URL}{self.target.id}/"

    def _patch(self, payload):
        return self.client.patch(self.url, payload, format="json")

    def _stored(self):
        return User.objects.get(pk=self.target.pk)

    def _events(self):
        return UserEvent.objects.filter(user=self.target)

    def _assert_rejected(self, response, field):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])
        self.assertFalse(self._events().exists())

    def test_role_change_returns_the_profile_and_writes_an_audit_row(self):
        response = self._patch({"role": User.Role.ADMIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), USER_KEYS)
        self.assertEqual(response.data["role"], User.Role.ADMIN)
        self.assertEqual(self._stored().role, User.Role.ADMIN)
        event = self._events().get()
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.field_changed, "role")
        self.assertEqual(event.old_value, User.Role.AGENT)
        self.assertEqual(event.new_value, User.Role.ADMIN)

    def test_every_role_can_be_assigned(self):
        for role in (User.Role.CUSTOMER, User.Role.ADMIN, User.Role.AGENT):
            with self.subTest(role=role):
                self.assertEqual(self._patch({"role": role}).status_code, 200)
                self.assertEqual(self._stored().role, role)
        self.assertEqual(self._events().count(), 3)

    def test_unchanged_values_write_no_audit_row(self):
        response = self._patch({"role": User.Role.AGENT, "is_active": True})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._events().exists())

    def test_empty_patch_changes_nothing(self):
        response = self._patch({})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._events().exists())

    def test_deactivating_blocks_login_and_ends_existing_sessions(self):
        login = _login(self.target)
        access, refresh = login.data["access"], login.data["refresh"]
        response = self._patch({"is_active": False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        self.assertFalse(self._stored().is_active)
        self.assertEqual(_login(self.target).status_code, 401)
        self.assertEqual(_client_with_access(access).get("/api/tickets/").status_code, 401)
        self.assertFalse(_refresh_token_is_valid(refresh))
        event = self._events().get()
        self.assertEqual(event.field_changed, "is_active")
        self.assertEqual(event.old_value, "true")
        self.assertEqual(event.new_value, "false")
        self.assertEqual(event.actor, self.admin)

    def test_deactivating_leaves_assigned_tickets_alone(self):
        ticket = TicketFactory(assignee=self.target)
        self._patch({"is_active": False})
        ticket.refresh_from_db()
        self.assertEqual(ticket.assignee, self.target)

    def test_reactivating_restores_login_and_writes_an_audit_row(self):
        inactive = AgentFactory(is_active=False)
        response = self.client.patch(f"{URL}{inactive.id}/", {"is_active": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_active"])
        self.assertEqual(_login(inactive).status_code, 200)
        event = UserEvent.objects.get(user=inactive)
        self.assertEqual(event.old_value, "false")
        self.assertEqual(event.new_value, "true")

    def test_password_reset_replaces_the_password_and_ends_every_session(self):
        first = _login(self.target).data["refresh"]
        second = _login(self.target).data["refresh"]
        other = AgentFactory()
        other_refresh = _login(other).data["refresh"]

        response = self._patch({"password": NEW_PASSWORD})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("password", response.data)
        self.assertEqual(_login(self.target, "pass12345").status_code, 401)
        self.assertEqual(_login(self.target, NEW_PASSWORD).status_code, 200)
        self.assertFalse(_refresh_token_is_valid(first))
        self.assertFalse(_refresh_token_is_valid(second))
        self.assertTrue(_refresh_token_is_valid(other_refresh))

    def test_password_reset_audit_row_holds_no_secret(self):
        self._patch({"password": NEW_PASSWORD})
        event = self._events().get()
        self.assertEqual(event.field_changed, "password")
        self.assertEqual(event.old_value, "")
        self.assertEqual(event.new_value, "")
        self.assertEqual(event.actor, self.admin)
        self.assertNotIn(NEW_PASSWORD, f"{event.old_value}{event.new_value}{event}")

    def test_weak_passwords_are_rejected_and_change_nothing(self):
        refresh = _login(self.target).data["refresh"]
        for password in ("short1", "password", "83927461", "", "a1b2c3d4" * 17):
            with self.subTest(password=password[:12]):
                self._assert_rejected(self._patch({"password": password}), "password")
                self.assertTrue(self._stored().check_password("pass12345"))
                self.assertTrue(_refresh_token_is_valid(refresh))

    def test_password_similar_to_the_username_is_rejected(self):
        target = AgentFactory(username="mohammad")
        response = self.client.patch(f"{URL}{target.id}/", {"password": "mohammad1"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data["error"]["details"])
        self.assertFalse(UserEvent.objects.filter(user=target).exists())

    def test_password_is_not_trimmed(self):
        padded = f" {NEW_PASSWORD} "
        self.assertEqual(self._patch({"password": padded}).status_code, 200)
        self.assertTrue(self._stored().check_password(padded))
        self.assertFalse(self._stored().check_password(NEW_PASSWORD))

    def test_several_changes_in_one_request_write_one_row_each_in_order(self):
        response = self._patch(
            {"role": User.Role.ADMIN, "is_active": False, "password": NEW_PASSWORD}
        )
        self.assertEqual(response.status_code, 200)
        fields = list(self._events().values_list("field_changed", flat=True))
        self.assertEqual(fields, ["role", "is_active", "password"])

    def test_rejected_request_applies_nothing(self):
        response = self._patch({"role": User.Role.ADMIN, "password": "short1"})
        self._assert_rejected(response, "password")
        self.assertEqual(self._stored().role, User.Role.AGENT)

    def test_invalid_values_are_rejected(self):
        self._assert_rejected(self._patch({"role": "superuser"}), "role")
        self._assert_rejected(self._patch({"is_active": "maybe"}), "is_active")

    def test_other_fields_are_ignored(self):
        before = self._stored()
        response = self._patch(
            {
                "username": "renamed",
                "first_name": "Changed",
                "phone": "09351112233",
                "email": "someone@example.com",
                "is_staff": True,
                "is_superuser": True,
            }
        )
        self.assertEqual(response.status_code, 200)
        stored = self._stored()
        self.assertEqual(stored.username, before.username)
        self.assertEqual(stored.first_name, before.first_name)
        self.assertEqual(stored.phone, before.phone)
        self.assertEqual(stored.email, before.email)
        self.assertFalse(stored.is_staff)
        self.assertFalse(stored.is_superuser)
        self.assertFalse(self._events().exists())

    def test_unknown_user_returns_404(self):
        response = self.client.patch(f"{URL}999999/", {"role": "admin"}, format="json")
        self.assertEqual(response.status_code, 404)


class UserSelfGuardTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)
        self.url = f"{URL}{self.admin.id}/"

    def _patch(self, payload):
        return self.client.patch(self.url, payload, format="json")

    def _assert_rejected(self, response, *fields):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertEqual(set(response.data["error"]["details"]), set(fields))
        self.assertFalse(UserEvent.objects.exists())
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Role.ADMIN)
        self.assertTrue(self.admin.is_active)
        self.assertTrue(self.admin.check_password("pass12345"))

    def test_admin_cannot_demote_themselves(self):
        for role in (User.Role.AGENT, User.Role.CUSTOMER):
            with self.subTest(role=role):
                self._assert_rejected(self._patch({"role": role}), "role")

    def test_admin_cannot_deactivate_themselves(self):
        self._assert_rejected(self._patch({"is_active": False}), "is_active")
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_admin_cannot_reset_their_own_password_here(self):
        self._assert_rejected(self._patch({"password": NEW_PASSWORD}), "password")

    def test_every_violation_is_reported_together(self):
        response = self._patch(
            {"role": User.Role.AGENT, "is_active": False, "password": NEW_PASSWORD}
        )
        self._assert_rejected(response, "role", "is_active", "password")

    def test_resending_unchanged_values_is_accepted_without_an_audit_row(self):
        response = self._patch({"role": User.Role.ADMIN, "is_active": True})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserEvent.objects.exists())

    def test_another_admin_can_demote_and_deactivate_this_admin(self):
        other_admin = AdminFactory()
        other_client = _client_for(other_admin)

        demote = other_client.patch(self.url, {"role": User.Role.CUSTOMER}, format="json")
        self.assertEqual(demote.status_code, 200)
        deactivate = other_client.patch(self.url, {"is_active": False}, format="json")
        self.assertEqual(deactivate.status_code, 200)

        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Role.CUSTOMER)
        self.assertFalse(self.admin.is_active)
        events = UserEvent.objects.filter(user=self.admin)
        self.assertEqual(events.count(), 2)
        self.assertEqual({event.actor_id for event in events}, {other_admin.id})

    def test_admin_can_still_change_other_admins(self):
        other_admin = AdminFactory()
        response = self.client.patch(
            f"{URL}{other_admin.id}/", {"role": User.Role.AGENT}, format="json"
        )
        self.assertEqual(response.status_code, 200)
