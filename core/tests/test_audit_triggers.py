from django.db import DatabaseError, connection, transaction
from django.db.models import QuerySet
from django.test import TestCase

from accounts.models import UserEvent
from core.tests.factories import TicketFactory, UserFactory
from tickets.models import Ticket, TicketEvent


def _execute(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.rowcount


class TicketEventTriggerTests(TestCase):
    def setUp(self):
        self.ticket = TicketFactory()
        self.event = TicketEvent.objects.create(
            ticket=self.ticket,
            actor=None,
            field_changed="priority",
            old_value="low",
            new_value="high",
        )

    def test_raw_sql_cannot_update_a_ticket_event(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            _execute(
                "UPDATE tickets_ticketevent SET new_value = 'x' WHERE id = %s", [self.event.pk]
            )
        self.assertEqual(TicketEvent.objects.get(pk=self.event.pk).new_value, "high")

    def test_raw_sql_cannot_delete_a_ticket_event(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            _execute("DELETE FROM tickets_ticketevent WHERE id = %s", [self.event.pk])
        self.assertTrue(TicketEvent.objects.filter(pk=self.event.pk).exists())

    def test_hard_deleting_a_ticket_cannot_cascade_into_its_events(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            QuerySet.delete(Ticket.all_objects.filter(pk=self.ticket.pk))
        self.assertTrue(TicketEvent.objects.filter(pk=self.event.pk).exists())

    def test_the_purge_flag_allows_the_delete(self):
        with transaction.atomic():
            _execute("SET LOCAL app.allow_audit_purge = 'on'")
            deleted = _execute("DELETE FROM tickets_ticketevent WHERE id = %s", [self.event.pk])
        self.assertEqual(deleted, 1)
        self.assertFalse(TicketEvent.objects.filter(pk=self.event.pk).exists())


class UserEventTriggerTests(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.event = UserEvent.objects.create(
            user=self.user,
            actor=None,
            field_changed="role",
            old_value="customer",
            new_value="agent",
        )

    def test_raw_sql_cannot_update_a_user_event(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            _execute("UPDATE accounts_userevent SET new_value = 'x' WHERE id = %s", [self.event.pk])
        self.assertEqual(UserEvent.objects.get(pk=self.event.pk).new_value, "agent")

    def test_raw_sql_cannot_delete_a_user_event(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            _execute("DELETE FROM accounts_userevent WHERE id = %s", [self.event.pk])
        self.assertTrue(UserEvent.objects.filter(pk=self.event.pk).exists())

    def test_the_purge_flag_allows_the_delete(self):
        with transaction.atomic():
            _execute("SET LOCAL app.allow_audit_purge = 'on'")
            deleted = _execute("DELETE FROM accounts_userevent WHERE id = %s", [self.event.pk])
        self.assertEqual(deleted, 1)
