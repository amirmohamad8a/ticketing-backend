from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from chat.models import Visitor
from chat.retention import count_redactable_visitors, redact_stale_visitors
from core.tests.factories import TicketFactory, VisitorFactory
from tickets.models import Ticket

OLD = timezone.now() - timedelta(days=60)


def _chat_ticket(visitor, status):
    return TicketFactory(
        customer=None,
        visitor=visitor,
        site=visitor.site,
        channel=Ticket.Channel.CHAT,
        status=status,
    )


@override_settings(VISITOR_RETENTION_DAYS=30)
class VisitorRetentionTests(TestCase):
    def _visitor(self, **overrides):
        defaults = {
            "last_seen_at": OLD,
            "name": "Sara",
            "phone": "09123456789",
            "email": "sara@example.com",
        }
        defaults.update(overrides)
        return VisitorFactory(**defaults)

    def test_a_visitor_with_only_finished_tickets_is_redacted_but_kept(self):
        visitor = self._visitor()
        _chat_ticket(visitor, Ticket.Status.RESOLVED)
        self.assertEqual(redact_stale_visitors(), 1)
        visitor.refresh_from_db()
        self.assertEqual((visitor.name, visitor.phone, visitor.email), ("", "", ""))
        self.assertTrue(Visitor.objects.filter(pk=visitor.pk).exists())

    def test_a_visitor_with_an_unfinished_ticket_is_kept(self):
        visitor = self._visitor()
        _chat_ticket(visitor, Ticket.Status.OPEN)
        self.assertEqual(redact_stale_visitors(), 0)
        visitor.refresh_from_db()
        self.assertEqual(visitor.name, "Sara")

    def test_a_recently_seen_visitor_is_kept(self):
        visitor = self._visitor(last_seen_at=timezone.now() - timedelta(days=1))
        _chat_ticket(visitor, Ticket.Status.CLOSED)
        self.assertEqual(redact_stale_visitors(), 0)
        visitor.refresh_from_db()
        self.assertEqual(visitor.name, "Sara")

    def test_a_visitor_without_tickets_is_redacted(self):
        visitor = self._visitor()
        self.assertEqual(redact_stale_visitors(), 1)
        visitor.refresh_from_db()
        self.assertEqual(visitor.name, "")

    def test_redaction_is_idempotent(self):
        visitor = self._visitor()
        _chat_ticket(visitor, Ticket.Status.CLOSED)
        self.assertEqual(redact_stale_visitors(), 1)
        self.assertEqual(redact_stale_visitors(), 0)

    def test_the_count_helper_matches_the_job(self):
        self._visitor()
        redact_stale_visitors()
        self.assertEqual(count_redactable_visitors(), 0)


@override_settings(VISITOR_RETENTION_DAYS=30)
class PurgeVisitorsCommandTests(TestCase):
    def _visitor(self):
        visitor = VisitorFactory(
            last_seen_at=OLD, name="Sara", phone="09123456789", email="sara@example.com"
        )
        _chat_ticket(visitor, Ticket.Status.CLOSED)
        return visitor

    def test_the_command_redacts_and_reports(self):
        visitor = self._visitor()
        output = StringIO()
        call_command("purge_visitors", stdout=output)
        self.assertIn("Cleared the contact details of 1", output.getvalue())
        visitor.refresh_from_db()
        self.assertEqual(visitor.name, "")

    def test_the_dry_run_only_counts(self):
        visitor = self._visitor()
        output = StringIO()
        call_command("purge_visitors", "--dry-run", stdout=output)
        self.assertIn("would have their contact details cleared", output.getvalue())
        visitor.refresh_from_db()
        self.assertEqual(visitor.name, "Sara")

    def test_the_days_override_controls_the_cutoff(self):
        visitor = VisitorFactory(last_seen_at=timezone.now() - timedelta(days=5), name="Ali")
        output = StringIO()
        call_command("purge_visitors", "--days", "1", stdout=output)
        self.assertIn("Cleared the contact details of 1", output.getvalue())
        visitor.refresh_from_db()
        self.assertEqual(visitor.name, "")
