from django.test import TestCase

from rest_framework.exceptions import ValidationError

from core.tests.factories import (
    AgentFactory,
    CommentFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)
from tickets.reads import annotate_unread, mark_conversation_read, unread_count, visible_comments


class ReadStateTests(TestCase):
    def setUp(self):
        self.customer = UserFactory(role="customer")
        self.agent = AgentFactory()
        self.ticket = TicketFactory(customer=self.customer)

        self.c1 = CommentFactory(ticket=self.ticket, author=self.customer, body="c1")
        self.c2 = CommentFactory(ticket=self.ticket, author=self.agent, body="c2")
        self.c3 = CommentFactory(ticket=self.ticket, author=self.agent, body="c3", is_internal=True)

    def test_visible_comments_for_customer_excludes_internal(self):
        qs = visible_comments(self.ticket, user=self.customer)
        self.assertEqual(set(qs), {self.c1, self.c2})

    def test_visible_comments_for_agent_includes_internal(self):
        qs = visible_comments(self.ticket, user=self.agent)
        self.assertEqual(set(qs), {self.c1, self.c2, self.c3})

    def test_unread_count_for_customer_ignores_own_and_internal(self):
        self.assertEqual(unread_count(self.ticket, user=self.customer), 1)

    def test_unread_count_for_agent_includes_all_from_others(self):
        self.assertEqual(unread_count(self.ticket, user=self.agent), 1)

    def test_mark_conversation_read_updates_state(self):
        state = mark_conversation_read(self.ticket, comment_id=self.c2.pk, user=self.customer)
        self.assertEqual(state["last_read_comment_id"], self.c2.pk)
        self.assertEqual(state["unread_count"], 0)

    def test_mark_read_rejects_invisible_comment(self):
        with self.assertRaises(ValidationError):
            mark_conversation_read(self.ticket, comment_id=self.c3.pk, user=self.customer)

    def test_mark_read_rejects_unknown_comment(self):
        with self.assertRaises(ValidationError):
            mark_conversation_read(self.ticket, comment_id=999999, user=self.customer)

    def test_mark_read_without_id_marks_all(self):
        state = mark_conversation_read(self.ticket, user=self.customer)
        self.assertEqual(state["last_read_comment_id"], self.c2.pk)
        self.assertEqual(state["unread_count"], 0)

    def test_marker_only_moves_forward(self):
        mark_conversation_read(self.ticket, comment_id=self.c2.pk, user=self.customer)
        state = mark_conversation_read(self.ticket, comment_id=self.c1.pk, user=self.customer)
        self.assertEqual(state["last_read_comment_id"], self.c2.pk)

    def test_annotate_unread(self):
        tickets = annotate_unread(self.customer.tickets.all(), self.customer)
        self.assertEqual(tickets.first().unread_count, 1)


class VisitorReadStateTests(TestCase):
    def setUp(self):
        self.visitor = VisitorFactory()
        self.ticket = TicketFactory(
            visitor=self.visitor, customer=None, site=self.visitor.site, channel="chat"
        )
        self.agent = AgentFactory()
        self.c1 = CommentFactory(ticket=self.ticket, visitor=self.visitor, author=None, body="v1")
        self.c2 = CommentFactory(ticket=self.ticket, author=self.agent, body="a1")
        self.c3 = CommentFactory(ticket=self.ticket, author=self.agent, body="a2", is_internal=True)

    def test_visitor_unread_ignores_internal_and_own(self):
        self.assertEqual(unread_count(self.ticket, visitor=self.visitor), 1)

    def test_visitor_mark_read(self):
        state = mark_conversation_read(self.ticket, comment_id=self.c2.pk, visitor=self.visitor)
        self.assertEqual(state["unread_count"], 0)
