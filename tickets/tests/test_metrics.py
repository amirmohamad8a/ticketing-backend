from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase

from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import AdminFactory, AgentFactory, TicketFactory, UserFactory
from tickets.lifecycle import change_status
from tickets.messages import post_message
from tickets.models import Comment, Ticket
from tickets.participants import Participant

T1 = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)
T2 = T1 + timedelta(hours=1)
T3 = T1 + timedelta(hours=2)
T4 = T1 + timedelta(hours=3)
T5 = T1 + timedelta(hours=4)


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _frozen(moment):
    return patch("django.utils.timezone.now", return_value=moment)


class FirstResponseTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.admin = AdminFactory()
        self.ticket = TicketFactory(customer=self.customer)

    def _stored(self, ticket=None):
        ticket = ticket or self.ticket
        return Ticket.objects.values_list("first_response_at", flat=True).get(pk=ticket.pk)

    def test_a_new_ticket_has_no_first_response(self):
        self.assertIsNone(self._stored())

    def test_the_first_public_staff_reply_sets_the_time(self):
        with _frozen(T1):
            comment, created = post_message(self.ticket, "Hello", Participant(self.agent))
        self.assertTrue(created)
        self.assertEqual(comment.created_at, T1)
        self.assertEqual(self._stored(), T1)
        self.assertEqual(self.ticket.first_response_at, T1)

    def test_it_is_set_only_once(self):
        with _frozen(T1):
            post_message(self.ticket, "First", Participant(self.agent))
        with _frozen(T2):
            post_message(self.ticket, "Second", Participant(self.agent))
        with _frozen(T3):
            post_message(self.ticket, "Third", Participant(self.admin))
        self.assertEqual(self._stored(), T1)

    def test_an_admin_reply_counts(self):
        with _frozen(T1):
            post_message(self.ticket, "Hello", Participant(self.admin))
        self.assertEqual(self._stored(), T1)

    def test_internal_notes_do_not_count(self):
        with _frozen(T1):
            post_message(self.ticket, "Note", Participant(self.agent), is_internal=True)
        self.assertIsNone(self._stored())
        with _frozen(T2):
            post_message(self.ticket, "Reply", Participant(self.agent))
        self.assertEqual(self._stored(), T2)

    def test_customer_messages_do_not_count(self):
        post_message(self.ticket, "Anyone there?", Participant(self.customer))
        self.assertIsNone(self._stored())

    def test_visitor_messages_do_not_count(self):
        ticket = TicketFactory(from_visitor=True)
        post_message(ticket, "Hello", Participant(visitor=ticket.visitor))
        self.assertIsNone(self._stored(ticket))

    def test_system_messages_do_not_count(self):
        post_message(self.ticket, "Notice", kind=Comment.Kind.SYSTEM)
        self.assertIsNone(self._stored())

    def test_an_existing_value_is_never_overwritten(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(first_response_at=T1)
        with _frozen(T2):
            post_message(self.ticket, "Late reply", Participant(self.agent))
        self.assertEqual(self._stored(), T1)

    def test_a_retried_message_does_not_change_it(self):
        with _frozen(T1):
            post_message(self.ticket, "Hello", Participant(self.agent), client_msg_id="m1")
        with _frozen(T2):
            _comment, created = post_message(
                self.ticket, "Hello", Participant(self.agent), client_msg_id="m1"
            )
        self.assertFalse(created)
        self.assertEqual(self._stored(), T1)

    def test_a_staff_comment_through_the_api_sets_it(self):
        response = _client_for(self.agent).post(
            f"/api/tickets/{self.ticket.id}/comments/", {"body": "Hi"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(self._stored())

    def test_internal_and_customer_comments_through_the_api_do_not(self):
        staff = _client_for(self.agent)
        owner = _client_for(self.customer)
        url = f"/api/tickets/{self.ticket.id}/comments/"
        staff.post(url, {"body": "Note", "is_internal": True}, format="json")
        owner.post(url, {"body": "Question"}, format="json")
        self.assertIsNone(self._stored())

    def test_the_value_is_not_exposed_through_the_api(self):
        response = _client_for(self.agent).get(f"/api/tickets/{self.ticket.id}/")
        self.assertNotIn("first_response_at", response.data)
        self.assertNotIn("resolved_at", response.data)


class ResolvedAtTests(TestCase):
    def _stored(self, ticket):
        return Ticket.objects.values_list("resolved_at", flat=True).get(pk=ticket.pk)

    def test_resolved_at_follows_the_ticket_through_its_lifecycle(self):
        ticket = TicketFactory()
        with _frozen(T1):
            change_status(ticket, Ticket.Status.IN_PROGRESS)
        self.assertIsNone(self._stored(ticket))
        with _frozen(T2):
            change_status(ticket, Ticket.Status.RESOLVED)
        self.assertEqual(self._stored(ticket), T2)
        with _frozen(T3):
            change_status(ticket, Ticket.Status.CLOSED)
        self.assertEqual(self._stored(ticket), T2)
        with _frozen(T4):
            change_status(ticket, Ticket.Status.IN_PROGRESS)
        self.assertIsNone(self._stored(ticket))
        with _frozen(T5):
            change_status(ticket, Ticket.Status.RESOLVED)
        self.assertEqual(self._stored(ticket), T5)

    def test_resolving_from_waiting_on_customer_sets_it(self):
        ticket = TicketFactory(status=Ticket.Status.WAITING_ON_CUSTOMER)
        with _frozen(T1):
            change_status(ticket, Ticket.Status.RESOLVED)
        self.assertEqual(self._stored(ticket), T1)

    def test_moving_between_unfinished_statuses_keeps_it_empty(self):
        ticket = TicketFactory()
        change_status(ticket, Ticket.Status.IN_PROGRESS)
        change_status(ticket, Ticket.Status.WAITING_ON_CUSTOMER)
        change_status(ticket, Ticket.Status.IN_PROGRESS)
        change_status(ticket, Ticket.Status.OPEN)
        self.assertIsNone(self._stored(ticket))

    def test_repeating_the_current_status_changes_nothing(self):
        ticket = TicketFactory(status=Ticket.Status.RESOLVED, resolved_at=T1)
        with _frozen(T2):
            change_status(ticket, Ticket.Status.RESOLVED)
        self.assertEqual(self._stored(ticket), T1)

    def test_an_illegal_transition_leaves_it_untouched(self):
        ticket = TicketFactory()
        with self.assertRaises(ValidationError):
            change_status(ticket, Ticket.Status.RESOLVED)
        self.assertIsNone(self._stored(ticket))
        self.assertEqual(Ticket.objects.get(pk=ticket.pk).status, Ticket.Status.OPEN)

    def test_the_api_sets_keeps_and_clears_it(self):
        ticket = TicketFactory()
        client = _client_for(AgentFactory())
        url = f"/api/tickets/{ticket.id}/"

        def move(status):
            response = client.patch(url, {"status": status}, format="json")
            self.assertEqual(response.status_code, 200)
            return self._stored(ticket)

        self.assertIsNone(move(Ticket.Status.IN_PROGRESS))
        resolved_at = move(Ticket.Status.RESOLVED)
        self.assertIsNotNone(resolved_at)
        self.assertEqual(move(Ticket.Status.CLOSED), resolved_at)
        self.assertIsNone(move(Ticket.Status.IN_PROGRESS))
