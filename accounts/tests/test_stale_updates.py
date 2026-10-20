from django.test import TestCase
from django.utils import timezone

from accounts.events import UserEventField
from accounts.models import User, UserEvent
from accounts.services import change_own_password, update_user
from core.tests.factories import AdminFactory, AgentFactory

NEW_PASSWORD = "Fresh-pass-8431"


class UpdateUserStaleInstanceTests(TestCase):
    def setUp(self):
        self.actor = AdminFactory()
        self.user = AgentFactory()

    def test_a_stale_save_does_not_overwrite_a_concurrent_password_change(self):
        stale = User.objects.get(pk=self.user.pk)
        change_own_password(User.objects.get(pk=self.user.pk), NEW_PASSWORD)

        update_user(stale, self.actor, {"is_active": False})

        stored = User.objects.get(pk=self.user.pk)
        self.assertTrue(stored.check_password(NEW_PASSWORD))
        self.assertFalse(stored.is_active)

    def test_a_stale_save_does_not_overwrite_last_chat_assigned_at(self):
        stale = User.objects.get(pk=self.user.pk)
        assigned_at = timezone.now()
        User.objects.filter(pk=self.user.pk).update(last_chat_assigned_at=assigned_at)

        update_user(stale, self.actor, {"role": User.Role.ADMIN})

        stored = User.objects.get(pk=self.user.pk)
        self.assertEqual(stored.role, User.Role.ADMIN)
        self.assertEqual(stored.last_chat_assigned_at, assigned_at)

    def test_events_are_computed_against_the_stored_role(self):
        stale = User.objects.get(pk=self.user.pk)
        User.objects.filter(pk=self.user.pk).update(role=User.Role.ADMIN)

        result = update_user(stale, self.actor, {"role": User.Role.AGENT})

        self.assertEqual(result.role, User.Role.AGENT)
        event = UserEvent.objects.get(user=self.user, field_changed=UserEventField.ROLE)
        self.assertEqual((event.old_value, event.new_value), ("admin", "agent"))
