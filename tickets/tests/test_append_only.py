from django.db import transaction
from django.test import TestCase

from core.models import AppendOnlyError
from core.tests.factories import TicketEventFactory
from tickets.models import Ticket, TicketEvent


class TicketEventAppendOnlyTests(TestCase):
    def setUp(self):
        self.event = TicketEventFactory()

    def _stored_value(self):
        return TicketEvent.objects.values_list("new_value", flat=True).get(pk=self.event.pk)

    def test_new_events_can_still_be_created(self):
        event = TicketEvent.objects.create(
            ticket=self.event.ticket,
            actor=self.event.actor,
            field_changed="status",
            old_value=Ticket.Status.IN_PROGRESS,
            new_value=Ticket.Status.RESOLVED,
        )
        self.assertIsNotNone(event.pk)
        self.assertEqual(TicketEvent.objects.count(), 2)

    def test_save_on_an_existing_event_raises(self):
        self.event.new_value = Ticket.Status.CLOSED
        with self.assertRaises(AppendOnlyError):
            self.event.save()
        self.assertEqual(self._stored_value(), Ticket.Status.IN_PROGRESS)

    def test_save_with_update_fields_raises(self):
        self.event.new_value = Ticket.Status.CLOSED
        with self.assertRaises(AppendOnlyError):
            self.event.save(update_fields=["new_value"])
        self.assertEqual(self._stored_value(), Ticket.Status.IN_PROGRESS)

    def test_save_with_an_existing_primary_key_raises(self):
        clone = TicketEvent(
            pk=self.event.pk,
            ticket=self.event.ticket,
            actor=self.event.actor,
            field_changed="status",
            old_value=Ticket.Status.OPEN,
            new_value=Ticket.Status.CLOSED,
        )
        with self.assertRaises(AppendOnlyError):
            clone.save()
        self.assertEqual(self._stored_value(), Ticket.Status.IN_PROGRESS)

    def test_instance_delete_raises(self):
        with self.assertRaises(AppendOnlyError):
            self.event.delete()
        self.assertTrue(TicketEvent.objects.filter(pk=self.event.pk).exists())

    def test_queryset_update_raises(self):
        with self.assertRaises(AppendOnlyError):
            TicketEvent.objects.update(new_value=Ticket.Status.CLOSED)
        with self.assertRaises(AppendOnlyError):
            TicketEvent.objects.filter(pk=self.event.pk).update(new_value=Ticket.Status.CLOSED)
        self.assertEqual(self._stored_value(), Ticket.Status.IN_PROGRESS)

    def test_queryset_delete_raises(self):
        with self.assertRaises(AppendOnlyError):
            TicketEvent.objects.all().delete()
        with self.assertRaises(AppendOnlyError):
            TicketEvent.objects.filter(pk=self.event.pk).delete()
        self.assertEqual(TicketEvent.objects.count(), 1)

    def test_related_manager_cannot_update_or_delete(self):
        ticket = self.event.ticket
        with self.assertRaises(AppendOnlyError):
            ticket.events.update(new_value=Ticket.Status.CLOSED)
        with self.assertRaises(AppendOnlyError):
            ticket.events.all().delete()
        self.assertEqual(ticket.events.count(), 1)
        self.assertEqual(self._stored_value(), Ticket.Status.IN_PROGRESS)

    def test_bulk_update_raises(self):
        self.event.new_value = Ticket.Status.CLOSED
        with self.assertRaises(AppendOnlyError):
            with transaction.atomic():
                TicketEvent.objects.bulk_update([self.event], ["new_value"])
        self.assertEqual(self._stored_value(), Ticket.Status.IN_PROGRESS)

    def test_update_or_create_on_an_existing_row_raises(self):
        with self.assertRaises(AppendOnlyError):
            with transaction.atomic():
                TicketEvent.objects.update_or_create(
                    pk=self.event.pk, defaults={"new_value": Ticket.Status.CLOSED}
                )
        self.assertEqual(self._stored_value(), Ticket.Status.IN_PROGRESS)
