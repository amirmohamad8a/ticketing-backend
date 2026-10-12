from django.contrib.admin.sites import site
from django.db.models import ProtectedError
from django.test import TestCase

from accounts.models import User, UserEvent
from core.models import AppendOnlyError
from core.tests.factories import AdminFactory, AgentFactory


class UserEventModelTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.target = AgentFactory()
        self.event = UserEvent.objects.create(
            user=self.target,
            actor=self.admin,
            field_changed="role",
            old_value=User.Role.AGENT,
            new_value=User.Role.ADMIN,
        )

    def _stored_value(self):
        return UserEvent.objects.values_list("new_value", flat=True).get(pk=self.event.pk)

    def test_str_representation(self):
        self.assertEqual(
            str(self.event),
            f"User #{self.target.pk} role: {User.Role.AGENT} -> {User.Role.ADMIN}",
        )

    def test_old_and_new_values_default_to_empty_strings(self):
        event = UserEvent.objects.create(user=self.target, actor=self.admin, field_changed="x")
        self.assertEqual((event.old_value, event.new_value), ("", ""))
        self.assertIsNotNone(event.created_at)

    def test_events_are_ordered_chronologically(self):
        second = UserEvent.objects.create(
            user=self.target, actor=self.admin, field_changed="is_active"
        )
        self.assertEqual(list(self.target.audit_events.all()), [self.event, second])

    def test_existing_events_cannot_be_modified(self):
        self.event.new_value = User.Role.CUSTOMER
        with self.assertRaises(AppendOnlyError):
            self.event.save()
        with self.assertRaises(AppendOnlyError):
            self.event.save(update_fields=["new_value"])
        self.assertEqual(self._stored_value(), User.Role.ADMIN)

    def test_events_cannot_be_deleted(self):
        with self.assertRaises(AppendOnlyError):
            self.event.delete()
        self.assertTrue(UserEvent.objects.filter(pk=self.event.pk).exists())

    def test_querysets_cannot_update_or_delete(self):
        with self.assertRaises(AppendOnlyError):
            UserEvent.objects.update(new_value=User.Role.CUSTOMER)
        with self.assertRaises(AppendOnlyError):
            UserEvent.objects.all().delete()
        with self.assertRaises(AppendOnlyError):
            self.target.audit_events.update(new_value=User.Role.CUSTOMER)
        self.assertEqual(self._stored_value(), User.Role.ADMIN)
        self.assertEqual(UserEvent.objects.count(), 1)

    def test_a_user_with_audit_history_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.target.delete()
        self.assertTrue(UserEvent.objects.filter(pk=self.event.pk).exists())

    def test_deleting_the_actor_keeps_the_event_and_clears_the_actor(self):
        self.admin.delete()
        self.event.refresh_from_db()
        self.assertIsNone(self.event.actor)


class UserEventAdminTests(TestCase):
    def test_user_event_is_registered_and_read_only_in_the_admin(self):
        self.assertIn(UserEvent, site._registry)
        admin_instance = site._registry[UserEvent]
        self.assertFalse(admin_instance.has_add_permission(request=None))
        self.assertFalse(admin_instance.has_change_permission(request=None))
        self.assertFalse(admin_instance.has_delete_permission(request=None))
