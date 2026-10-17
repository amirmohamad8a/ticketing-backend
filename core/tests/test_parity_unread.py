from django.test import TestCase

from core.tests.factories import (
    AgentFactory,
    CommentFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)
from tickets.models import Comment, ConversationRead, Ticket
from tickets.reads import annotate_unread, read_state, unread_count


class UnreadParityTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.first_agent = AgentFactory()
        self.second_agent = AgentFactory()
        self.visitor = VisitorFactory()
        self.ticket = TicketFactory(customer=self.customer)

        self.comments = [
            CommentFactory(ticket=self.ticket, author=self.customer, body="c1"),
            CommentFactory(ticket=self.ticket, author=self.first_agent, body="a1"),
            CommentFactory(
                ticket=self.ticket,
                author=None,
                visitor=None,
                kind=Comment.Kind.SYSTEM,
                body="system",
            ),
            CommentFactory(
                ticket=self.ticket,
                author=None,
                visitor=self.visitor,
                kind=Comment.Kind.MESSAGE,
                body="visitor",
            ),
            CommentFactory(
                ticket=self.ticket,
                author=self.first_agent,
                body="internal",
                is_internal=True,
            ),
            CommentFactory(ticket=self.ticket, author=self.second_agent, body="a2"),
        ]

        ConversationRead.objects.create(
            ticket=self.ticket, user=self.customer, last_read_comment_id=self.comments[0].pk
        )
        ConversationRead.objects.create(
            ticket=self.ticket, user=self.first_agent, last_read_comment_id=self.comments[2].pk
        )
        ConversationRead.objects.create(
            ticket=self.ticket, user=self.second_agent, last_read_comment_id=0
        )
        ConversationRead.objects.create(
            ticket=self.ticket, visitor=self.visitor, last_read_comment_id=self.comments[1].pk
        )

        another = TicketFactory(customer=self.customer)
        CommentFactory(ticket=another, author=self.first_agent)

    def _annotation(self, reader):
        queryset = annotate_unread(Ticket.objects.filter(pk=self.ticket.pk), reader)
        return queryset.get().unread_count

    def test_read_state_and_annotate_unread_agree_for_every_user_reader(self):
        for reader in (self.customer, self.first_agent, self.second_agent):
            with self.subTest(role=reader.role, username=reader.username):
                state = read_state(self.ticket, user=reader)
                self.assertEqual(state["unread_count"], unread_count(self.ticket, user=reader))
                self.assertEqual(state["unread_count"], self._annotation(reader))

    def test_the_visitor_reader_uses_the_same_rule_as_the_widget(self):
        state = read_state(self.ticket, visitor=self.visitor)
        self.assertEqual(state["last_read_comment_id"], self.comments[1].pk)
        self.assertEqual(
            state["unread_count"],
            sum(
                1
                for comment in self.comments[2:]
                if not comment.is_internal and comment.visitor_id != self.visitor.pk
            ),
        )
