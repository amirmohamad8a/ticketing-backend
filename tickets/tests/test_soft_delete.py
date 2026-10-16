from io import StringIO

from django.contrib.admin.sites import site
from django.core.management import call_command
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.demo import CHAT_TICKETS, PORTAL_TICKETS
from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    CommentFactory,
    TicketEventFactory,
    TicketFactory,
    UserFactory,
)
from tickets.models import Comment, Ticket, TicketEvent


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class SoftDeleteModelTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.ticket = TicketFactory(customer=self.customer, assignee=self.agent)

    def test_delete_hides_the_ticket_but_keeps_the_row(self):
        before = timezone.now()
        self.ticket.delete()
        after = timezone.now()
        self.assertFalse(Ticket.objects.filter(pk=self.ticket.pk).exists())
        stored = Ticket.all_objects.get(pk=self.ticket.pk)
        self.assertTrue(stored.is_deleted)
        self.assertGreaterEqual(stored.deleted_at, before)
        self.assertLessEqual(stored.deleted_at, after)

    def test_delete_is_idempotent_and_keeps_the_first_timestamp(self):
        self.ticket.delete()
        first = Ticket.all_objects.get(pk=self.ticket.pk).deleted_at
        loaded = Ticket.all_objects.get(pk=self.ticket.pk)
        self.assertEqual(loaded.delete(), (0, {}))
        Ticket.all_objects.all().delete()
        self.assertEqual(Ticket.all_objects.get(pk=self.ticket.pk).deleted_at, first)

    def test_queryset_delete_is_soft_and_reports_the_count(self):
        TicketFactory.create_batch(2)
        result = Ticket.objects.exclude(pk=self.ticket.pk).delete()
        self.assertEqual(result, (2, {"tickets.Ticket": 2}))
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(Ticket.all_objects.count(), 3)
        self.assertEqual(Ticket.objects.exclude(pk=self.ticket.pk).delete(), (0, {}))

    def test_manager_does_not_expose_a_bulk_delete(self):
        self.assertFalse(hasattr(Ticket.objects, "delete"))
        self.assertFalse(hasattr(Ticket.all_objects, "delete"))

    def test_deleted_helper_returns_only_deleted_rows(self):
        other = TicketFactory()
        self.ticket.delete()
        self.assertEqual(list(Ticket.all_objects.deleted()), [self.ticket])
        self.assertNotIn(other, Ticket.all_objects.deleted())

    def test_restore_brings_the_ticket_back(self):
        self.ticket.delete()
        self.ticket.restore()
        stored = Ticket.objects.get(pk=self.ticket.pk)
        self.assertFalse(stored.is_deleted)
        self.assertIsNone(stored.deleted_at)

    def test_queryset_restore_brings_back_every_deleted_ticket(self):
        TicketFactory.create_batch(2)
        Ticket.objects.all().delete()
        restored = Ticket.all_objects.deleted().restore()
        self.assertEqual(restored, 3)
        self.assertEqual(Ticket.objects.count(), 3)

    def test_related_managers_hide_deleted_tickets(self):
        self.assertEqual(self.customer.tickets.count(), 1)
        self.assertEqual(self.agent.assigned_tickets.count(), 1)
        self.ticket.delete()
        self.assertEqual(self.customer.tickets.count(), 0)
        self.assertEqual(self.agent.assigned_tickets.count(), 0)
        self.assertEqual(Ticket.all_objects.filter(customer=self.customer).count(), 1)

    def test_refresh_from_db_works_on_a_deleted_ticket(self):
        self.ticket.delete()
        self.ticket.refresh_from_db()
        self.assertTrue(self.ticket.is_deleted)

    def test_children_survive_deleting_the_ticket(self):
        event = TicketEventFactory(ticket=self.ticket)
        comment = CommentFactory(ticket=self.ticket)
        self.ticket.delete()
        self.assertTrue(TicketEvent.objects.filter(pk=event.pk).exists())
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_customer_with_only_a_deleted_ticket_is_still_protected(self):
        self.ticket.delete()
        with self.assertRaises(ProtectedError):
            self.customer.delete()

    def test_deleting_the_assignee_still_clears_a_deleted_ticket(self):
        self.ticket.delete()
        self.agent.delete()
        self.assertIsNone(Ticket.all_objects.get(pk=self.ticket.pk).assignee)


class TicketSoftDeleteApiTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.admin = AdminFactory()
        self.ticket = TicketFactory(customer=self.customer, assignee=self.agent)
        TicketEventFactory(ticket=self.ticket)
        CommentFactory(ticket=self.ticket, author=self.customer)
        self.url = f"/api/tickets/{self.ticket.id}/"
        self.admin_client = _client_for(self.admin)

    def _event_ids(self):
        return list(TicketEvent.objects.filter(ticket=self.ticket).values_list("id", flat=True))

    def test_admin_delete_returns_204_and_hides_the_ticket_everywhere(self):
        response = self.admin_client.delete(self.url)
        self.assertEqual(response.status_code, 204)
        for user in (self.admin, self.agent, self.customer):
            client = _client_for(user)
            for suffix in ("", "events/", "comments/", "attachments/"):
                with self.subTest(role=user.role, suffix=suffix):
                    self.assertEqual(client.get(f"{self.url}{suffix}").status_code, 404)

    def test_delete_keeps_every_audit_row_and_writes_no_new_one(self):
        before = self._event_ids()
        self.assertTrue(before)
        self.admin_client.delete(self.url)
        self.assertEqual(self._event_ids(), before)
        self.assertEqual(Comment.objects.filter(ticket=self.ticket).count(), 1)

    def test_deleted_ticket_is_missing_from_every_list(self):
        self.ticket.delete()
        for user in (self.admin, self.agent, self.customer):
            with self.subTest(role=user.role):
                response = _client_for(user).get("/api/tickets/")
                ids = {ticket["id"] for ticket in response.data["results"]}
                self.assertNotIn(self.ticket.id, ids)

    def test_agent_and_customer_cannot_delete(self):
        for user in (self.agent, self.customer):
            with self.subTest(role=user.role):
                response = _client_for(user).delete(self.url)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["error"]["code"], "permission_denied")
                self.assertTrue(Ticket.objects.filter(pk=self.ticket.pk).exists())

    def test_deleting_twice_returns_404(self):
        self.assertEqual(self.admin_client.delete(self.url).status_code, 204)
        self.assertEqual(self.admin_client.delete(self.url).status_code, 404)

    def test_admin_can_restore_a_deleted_ticket(self):
        self.ticket.delete()
        response = self.admin_client.post(f"{self.url}restore/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], self.ticket.id)
        restored = Ticket.objects.get(pk=self.ticket.pk)
        self.assertFalse(restored.is_deleted)
        self.assertIsNone(restored.deleted_at)
        self.assertEqual(_client_for(self.customer).get(self.url).status_code, 200)

    def test_restore_keeps_status_priority_and_assignee_and_writes_no_event(self):
        ticket = TicketFactory(
            customer=self.customer,
            assignee=self.agent,
            status=Ticket.Status.IN_PROGRESS,
            priority=Ticket.Priority.HIGH,
        )
        TicketEventFactory(ticket=ticket)
        ticket.delete()
        before = TicketEvent.objects.filter(ticket=ticket).count()
        response = self.admin_client.post(f"/api/tickets/{ticket.id}/restore/")
        self.assertEqual(response.status_code, 200)
        restored = Ticket.objects.get(pk=ticket.pk)
        self.assertEqual(restored.status, Ticket.Status.IN_PROGRESS)
        self.assertEqual(restored.priority, Ticket.Priority.HIGH)
        self.assertEqual(restored.assignee, self.agent)
        self.assertEqual(TicketEvent.objects.filter(ticket=ticket).count(), before)

    def test_only_admins_can_restore(self):
        self.ticket.delete()
        for user in (self.agent, self.customer):
            with self.subTest(role=user.role):
                response = _client_for(user).post(f"{self.url}restore/")
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["error"]["code"], "permission_denied")
                self.assertTrue(Ticket.all_objects.get(pk=self.ticket.pk).is_deleted)

    def test_restoring_a_live_ticket_returns_404(self):
        response = self.admin_client.post(f"{self.url}restore/")
        self.assertEqual(response.status_code, 404)

    def test_restoring_an_unknown_ticket_returns_404(self):
        response = self.admin_client.post("/api/tickets/999999/restore/")
        self.assertEqual(response.status_code, 404)


class TicketAdminSoftDeleteTests(TestCase):
    def test_admin_site_lists_deleted_tickets(self):
        ticket = TicketFactory()
        ticket.delete()
        admin_instance = site._registry[Ticket]
        self.assertIn(ticket, admin_instance.get_queryset(None))

    def test_admin_site_offers_a_restore_action_and_a_deleted_filter(self):
        admin_instance = site._registry[Ticket]
        self.assertIn("restore_selected", admin_instance.actions)
        self.assertIn("is_deleted", admin_instance.list_filter)


class SeedDemoSoftDeleteTests(TestCase):
    def test_rerun_restores_a_deleted_demo_ticket_without_duplicating_it(self):
        total = len(PORTAL_TICKETS) + len(CHAT_TICKETS)
        call_command("seed_demo", force=True, stdout=StringIO())
        Ticket.objects.first().delete()
        call_command("seed_demo", force=True, stdout=StringIO())
        self.assertEqual(Ticket.all_objects.count(), total)
        self.assertEqual(Ticket.objects.count(), total)
