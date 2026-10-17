from types import SimpleNamespace

from django.contrib.admin.sites import site
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.test import TestCase, override_settings

from accounts.admin import _join, _m2m_labels
from accounts.models import User, UserEvent
from core.tests.factories import AgentFactory, TicketFactory

NEW_PASSWORD = "Reset-pass-6074"
ADMIN_LOGIN_URL = "/admin/login/"


class _FakeForm:
    def __init__(self, instance, on_save=None):
        self.instance = instance
        self._on_save = on_save

    def save_m2m(self):
        if self._on_save is not None:
            self._on_save()


class UserAdminAuditTests(TestCase):
    def setUp(self):
        self.admin = AgentFactory(role=User.Role.ADMIN)
        self.target = AgentFactory()
        self.admin_instance = site._registry[User]
        self.request = SimpleNamespace(user=self.admin)

    def _events(self):
        return UserEvent.objects.filter(user=self.target)

    def _fields(self):
        return set(self._events().values_list("field_changed", flat=True))

    def test_users_cannot_be_deleted_through_the_admin(self):
        self.assertFalse(self.admin_instance.has_delete_permission(None))

    def test_creation_writes_a_created_event(self):
        user = User(username="adminmade", role=User.Role.AGENT)
        self.admin_instance.save_model(self.request, user, None, False)
        event = UserEvent.objects.get(user=user)
        self.assertEqual(event.field_changed, "created")
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.new_value, User.Role.AGENT)

    def test_role_and_active_changes_write_one_event_each(self):
        self.target.role = User.Role.CUSTOMER
        self.target.is_active = False
        self.admin_instance.save_model(self.request, self.target, None, True)
        self.assertEqual(self._fields(), {"role", "is_active"})
        events = {event.field_changed: event for event in self._events()}
        self.assertEqual(events["role"].old_value, User.Role.AGENT)
        self.assertEqual(events["role"].new_value, User.Role.CUSTOMER)
        self.assertEqual(events["is_active"].old_value, "true")
        self.assertEqual(events["is_active"].new_value, "false")
        self.assertEqual({event.actor for event in self._events()}, {self.admin})

    def test_staff_and_superuser_changes_are_audited(self):
        self.target.is_staff = True
        self.target.is_superuser = True
        self.admin_instance.save_model(self.request, self.target, None, True)
        self.assertEqual(self._fields(), {"is_staff", "is_superuser"})

    def test_an_unchanged_save_writes_no_event(self):
        self.admin_instance.save_model(self.request, self.target, None, True)
        self.assertFalse(self._events().exists())

    def test_deactivating_an_agent_releases_open_tickets(self):
        ticket = TicketFactory(assignee=self.target)
        self.target.is_active = False
        self.admin_instance.save_model(self.request, self.target, None, True)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.assignee)

    def test_demoting_an_agent_releases_open_tickets(self):
        ticket = TicketFactory(assignee=self.target)
        self.target.role = User.Role.CUSTOMER
        self.admin_instance.save_model(self.request, self.target, None, True)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.assignee)

    def test_group_changes_are_audited(self):
        group = Group.objects.create(name="editors")
        form = _FakeForm(self.target, on_save=lambda: self.target.groups.add(group))
        self.admin_instance.save_related(self.request, form, [], True)
        event = self._events().get()
        self.assertEqual(event.field_changed, "groups")
        self.assertEqual(event.old_value, "")
        self.assertEqual(event.new_value, "editors")
        self.assertEqual(event.actor, self.admin)

    def test_permission_changes_are_audited(self):
        permission = Permission.objects.get(codename="add_tag")
        form = _FakeForm(self.target, on_save=lambda: self.target.user_permissions.add(permission))
        self.admin_instance.save_related(self.request, form, [], True)
        event = self._events().get()
        self.assertEqual(event.field_changed, "user_permissions")
        self.assertEqual(event.new_value, "tickets.add_tag")

    def test_unchanged_related_data_writes_no_event(self):
        self.admin_instance.save_related(self.request, _FakeForm(self.target), [], True)
        self.assertFalse(self._events().exists())

    def test_related_data_on_creation_writes_no_event(self):
        self.admin_instance.save_related(self.request, _FakeForm(self.target), [], False)
        self.assertFalse(self._events().exists())

    def test_join_truncates_long_values(self):
        self.assertEqual(_join({"b", "a"}), "a, b")
        self.assertEqual(len(_join({"x" * 300})), 255)

    def test_m2m_labels_read_groups_and_permissions(self):
        group = Group.objects.create(name="editors")
        self.target.groups.add(group)
        self.assertEqual(_m2m_labels(self.target, "groups"), {"editors"})
        self.assertEqual(_m2m_labels(self.target, "user_permissions"), set())


class UserAdminPasswordChangeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="root", password="pass12345")
        self.client.force_login(self.admin)
        self.target = AgentFactory()

    def test_changing_a_password_through_the_admin_is_audited(self):
        url = f"/admin/accounts/user/{self.target.pk}/password/"
        response = self.client.post(url, {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
        self.assertEqual(response.status_code, 302)
        event = UserEvent.objects.get(user=self.target)
        self.assertEqual(event.field_changed, "password")
        self.assertEqual((event.old_value, event.new_value), ("", ""))
        self.assertEqual(event.actor, self.admin)
        self.assertTrue(
            self.target.__class__.objects.get(pk=self.target.pk).check_password(NEW_PASSWORD)
        )


class AdminLoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _attempt(self, **extra):
        payload = {"username": "ghost", "password": "wrong-pass"}
        return self.client.post(ADMIN_LOGIN_URL, payload, **extra)

    @override_settings(ADMIN_LOGIN_MAX_ATTEMPTS=2, ADMIN_LOGIN_WINDOW_SECONDS=300)
    def test_repeated_attempts_are_throttled(self):
        statuses = [self._attempt().status_code for _ in range(3)]
        self.assertEqual(statuses, [200, 200, 429])

    @override_settings(ADMIN_LOGIN_MAX_ATTEMPTS=2)
    def test_the_login_page_is_never_limited(self):
        for _ in range(5):
            self.assertEqual(self.client.get(ADMIN_LOGIN_URL).status_code, 200)

    @override_settings(ADMIN_LOGIN_MAX_ATTEMPTS=1)
    def test_each_address_has_its_own_budget(self):
        first = self._attempt()
        blocked = self._attempt()
        other = self._attempt(REMOTE_ADDR="10.9.9.9")
        self.assertEqual(
            (first.status_code, blocked.status_code, other.status_code), (200, 429, 200)
        )

    @override_settings(ADMIN_LOGIN_MAX_ATTEMPTS=0)
    def test_the_limiter_can_be_disabled(self):
        statuses = [self._attempt().status_code for _ in range(5)]
        self.assertEqual(statuses, [200] * 5)
