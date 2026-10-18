from django.test import TestCase

from core.errors import DomainValidationError
from core.tests.factories import AgentFactory, TagFactory, TicketFactory, UserFactory
from tickets.models import Ticket
from tickets.rules import validate_assignee, validate_status_transition, validate_tags


class StatusTransitionRuleTests(TestCase):
    def test_a_valid_transition_is_returned(self):
        ticket = TicketFactory(status=Ticket.Status.OPEN)
        self.assertEqual(
            validate_status_transition(ticket, Ticket.Status.IN_PROGRESS),
            Ticket.Status.IN_PROGRESS,
        )

    def test_the_current_status_is_allowed(self):
        ticket = TicketFactory(status=Ticket.Status.RESOLVED)
        self.assertEqual(
            validate_status_transition(ticket, Ticket.Status.RESOLVED), Ticket.Status.RESOLVED
        )

    def test_an_illegal_transition_reports_the_status_field(self):
        ticket = TicketFactory(status=Ticket.Status.OPEN)
        with self.assertRaises(DomainValidationError) as caught:
            validate_status_transition(ticket, Ticket.Status.RESOLVED)
        self.assertEqual(
            caught.exception.field_errors,
            {"status": ["Cannot transition status from 'open' to 'resolved'."]},
        )


class AssigneeRuleTests(TestCase):
    def test_unassigning_is_allowed(self):
        self.assertIsNone(validate_assignee(None))

    def test_the_current_assignee_is_allowed_even_when_inactive(self):
        assignee = AgentFactory(is_active=False)
        self.assertEqual(validate_assignee(assignee, assignee), assignee)

    def test_an_active_agent_is_allowed(self):
        assignee = AgentFactory()
        self.assertEqual(validate_assignee(assignee), assignee)

    def test_a_customer_is_rejected(self):
        with self.assertRaises(DomainValidationError) as caught:
            validate_assignee(UserFactory())
        self.assertEqual(
            caught.exception.field_errors,
            {"assignee": ["Tickets can only be assigned to an agent or admin."]},
        )

    def test_an_inactive_user_is_rejected(self):
        with self.assertRaises(DomainValidationError) as caught:
            validate_assignee(AgentFactory(is_active=False))
        self.assertEqual(
            caught.exception.field_errors,
            {"assignee": ["Tickets cannot be assigned to an inactive user."]},
        )


class TagRuleTests(TestCase):
    def test_duplicate_tags_are_collapsed(self):
        tag = TagFactory()
        self.assertEqual(validate_tags([tag, tag]), [tag])

    def test_the_limit_is_ten_tags(self):
        tags = TagFactory.create_batch(11)
        with self.assertRaises(DomainValidationError) as caught:
            validate_tags(tags)
        self.assertEqual(
            caught.exception.field_errors,
            {"tags": ["A ticket can have at most 10 tags."]},
        )

    def test_ten_tags_are_allowed(self):
        tags = TagFactory.create_batch(10)
        self.assertEqual(validate_tags(tags), tags)
