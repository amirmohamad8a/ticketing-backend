from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from chat.offline import convert_due_chats
from core.tests.factories import (
    AgentFactory,
    SiteFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)
from tickets.messages import post_message
from tickets.models import Ticket

SLA_MINUTES = {"low": 1440, "medium": 480, "high": 240, "urgent": 60}


class FirstResponseContractTests(TestCase):
    def setUp(self):
        self.ticket = TicketFactory()
        self.agent = AgentFactory()
        self.customer = UserFactory()

    def test_first_response_at_is_set_once_by_the_first_public_staff_reply(self):
        self.assertIsNone(self.ticket.first_response_at)

        internal, _ = post_message(self.ticket, "internal", author=self.agent, is_internal=True)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.first_response_at)

        post_message(self.ticket, "customer", author=self.customer)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.first_response_at)

        first, _ = post_message(self.ticket, "first reply", author=self.agent)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.first_response_at, first.created_at)

        post_message(self.ticket, "second reply", author=self.agent)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.first_response_at, first.created_at)


@override_settings(SLA_FIRST_RESPONSE_MINUTES=SLA_MINUTES)
class DueDateContractTests(TestCase):
    def test_priority_changes_through_update_fields_move_the_due_date(self):
        now = timezone.now()
        ticket = TicketFactory(priority=Ticket.Priority.LOW)
        Ticket.objects.filter(pk=ticket.pk).update(created_at=now)
        ticket.refresh_from_db()
        ticket.save(update_fields=["priority"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.first_response_due_at, now + timedelta(minutes=1440))

        ticket.priority = Ticket.Priority.URGENT
        ticket.save(update_fields=["priority"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.first_response_due_at, now + timedelta(minutes=60))

        moved = now + timedelta(days=30)
        Ticket.objects.filter(pk=ticket.pk).update(first_response_due_at=moved)
        ticket.refresh_from_db()
        ticket.title = "Renamed"
        ticket.save(update_fields=["title"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.first_response_due_at, moved)


class OfflineSweepContractTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.site = SiteFactory(offline_timeout_minutes=5)
        self.visitor = VisitorFactory(site=self.site)
        self.ticket = TicketFactory(
            from_visitor=True, visitor=self.visitor, status=Ticket.Status.OPEN
        )
        self.start = timezone.now()

    def test_an_early_candidate_is_only_converted_after_a_second_sweep(self):
        self.assertEqual(convert_due_chats(now=self.start + timedelta(minutes=1)), 0)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.channel, Ticket.Channel.CHAT)
        self.assertEqual(self.ticket.status, Ticket.Status.OPEN)

        self.assertEqual(convert_due_chats(now=self.start + timedelta(minutes=2)), 1)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.channel, Ticket.Channel.OFFLINE_FORM)
