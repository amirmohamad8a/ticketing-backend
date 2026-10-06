from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase

from rest_framework.test import APIClient

from accounts.models import User
from core.management.commands.seed_demo import (
    AGENT_USERNAME,
    CUSTOMER_USERNAME,
    DEMO_PASSWORD,
    TICKETS,
)
from notifications.models import NotificationLog
from tickets.models import Comment, Ticket, TicketEvent


def _seed():
    call_command("seed_demo", stdout=StringIO())


def _counts():
    return (
        User.objects.count(),
        Ticket.objects.count(),
        Comment.objects.count(),
        TicketEvent.objects.count(),
    )


def _login(client, username):
    response = client.post("/api/token/", {"username": username, "password": DEMO_PASSWORD})
    return response


class SeedDemoTests(TestCase):
    def test_creates_demo_users_without_email_or_elevated_flags(self):
        _seed()
        customer = User.objects.get(username=CUSTOMER_USERNAME)
        agent = User.objects.get(username=AGENT_USERNAME)
        self.assertEqual(customer.role, User.Role.CUSTOMER)
        self.assertEqual(agent.role, User.Role.AGENT)
        for user in (customer, agent):
            self.assertEqual(user.email, "")
            self.assertTrue(user.check_password(DEMO_PASSWORD))
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)

    def test_creates_tickets_and_comments_including_internal_notes(self):
        _seed()
        self.assertEqual(Ticket.objects.count(), len(TICKETS))
        self.assertEqual(Comment.objects.count(), sum(len(spec["comments"]) for spec in TICKETS))
        self.assertTrue(Comment.objects.filter(is_internal=True).exists())
        customer = User.objects.get(username=CUSTOMER_USERNAME)
        self.assertEqual(Ticket.objects.filter(customer=customer).count(), len(TICKETS))

    def test_event_history_matches_the_final_state_of_each_ticket(self):
        _seed()
        for ticket in Ticket.objects.all():
            events = list(ticket.events.order_by("id"))
            self.assertEqual(events[0].field_changed, "created")
            self.assertEqual(events[0].new_value, Ticket.Status.OPEN)

            previous = Ticket.Status.OPEN
            for event in (e for e in events if e.field_changed == "status"):
                self.assertEqual(event.old_value, previous)
                self.assertIn(event.new_value, Ticket.STATUS_TRANSITIONS[previous])
                previous = event.new_value
            self.assertEqual(ticket.status, previous)

            assignee_events = [e for e in events if e.field_changed == "assignee"]
            if ticket.assignee:
                self.assertEqual(assignee_events[-1].new_value, ticket.assignee.username)
            else:
                self.assertEqual(assignee_events, [])

    def test_running_twice_creates_no_duplicates(self):
        _seed()
        first = _counts()
        _seed()
        self.assertEqual(_counts(), first)

    def test_rerun_restores_a_deleted_comment_without_duplicating_the_rest(self):
        _seed()
        first = _counts()
        Comment.objects.first().delete()
        _seed()
        self.assertEqual(_counts(), first)

    def test_rerun_does_not_reset_an_existing_users_password(self):
        _seed()
        user = User.objects.get(username=CUSTOMER_USERNAME)
        user.set_password("changed-pass-1")
        user.save()
        _seed()
        user.refresh_from_db()
        self.assertTrue(user.check_password("changed-pass-1"))

    def test_nothing_is_enqueued_or_mailed(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            _seed()
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(NotificationLog.objects.exists())

    def test_both_demo_users_can_sign_in(self):
        _seed()
        client = APIClient()
        for username in (CUSTOMER_USERNAME, AGENT_USERNAME):
            with self.subTest(username=username):
                response = _login(client, username)
                self.assertEqual(response.status_code, 200)
                self.assertIn("access", response.data)

    def test_demo_customer_sees_own_tickets_but_no_internal_comments(self):
        _seed()
        client = APIClient()
        token = _login(client, CUSTOMER_USERNAME).data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.get("/api/tickets/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), len(TICKETS))
        for ticket in Ticket.objects.all():
            comments = client.get(f"/api/tickets/{ticket.id}/comments/")
            self.assertEqual(comments.status_code, 200)
            self.assertFalse(any(comment["is_internal"] for comment in comments.data))

    def test_demo_agent_sees_every_demo_ticket_and_internal_comments(self):
        _seed()
        client = APIClient()
        token = _login(client, AGENT_USERNAME).data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.get("/api/tickets/")
        self.assertEqual(len(response.data["results"]), len(TICKETS))
        internal_seen = 0
        for ticket in Ticket.objects.all():
            comments = client.get(f"/api/tickets/{ticket.id}/comments/")
            internal_seen += sum(1 for comment in comments.data if comment["is_internal"])
        self.assertEqual(internal_seen, Comment.objects.filter(is_internal=True).count())
