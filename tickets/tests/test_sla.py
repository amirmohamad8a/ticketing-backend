from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    CommentFactory,
    TicketFactory,
    UserFactory,
)
from tickets.models import Comment, Ticket
from tickets.overdue import filter_overdue, overdue_ticket_ids
from tickets.sla import compute_first_response_due_at, first_response_minutes

URL = "/api/tickets/"
NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
SLA_MINUTES = {"low": 1440, "medium": 480, "high": 240, "urgent": 60}
PAST = timedelta(hours=-1)
FUTURE = timedelta(hours=1)


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _frozen(moment):
    return patch("django.utils.timezone.now", return_value=moment)


@override_settings(SLA_FIRST_RESPONSE_MINUTES=SLA_MINUTES)
class SlaFunctionTests(SimpleTestCase):
    def test_every_priority_has_a_target(self):
        for priority, minutes in SLA_MINUTES.items():
            with self.subTest(priority=priority):
                self.assertEqual(first_response_minutes(priority), minutes)

    def test_the_due_date_adds_the_target_to_the_start(self):
        for priority, minutes in SLA_MINUTES.items():
            with self.subTest(priority=priority):
                due = compute_first_response_due_at(priority, NOW)
                self.assertEqual(due, NOW + timedelta(minutes=minutes))

    def test_an_unknown_priority_is_an_error(self):
        with self.assertRaises(KeyError):
            first_response_minutes("critical")

    def test_the_targets_come_from_the_settings(self):
        with override_settings(SLA_FIRST_RESPONSE_MINUTES={**SLA_MINUTES, "urgent": 5}):
            self.assertEqual(first_response_minutes("urgent"), 5)
            self.assertEqual(
                compute_first_response_due_at("urgent", NOW), NOW + timedelta(minutes=5)
            )


@override_settings(SLA_FIRST_RESPONSE_MINUTES=SLA_MINUTES)
class TicketDueDateTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()

    def _create(self, **kwargs):
        with _frozen(NOW):
            return TicketFactory(**kwargs)

    def test_every_priority_gets_its_own_due_date(self):
        for priority, minutes in SLA_MINUTES.items():
            with self.subTest(priority=priority):
                ticket = self._create(priority=priority)
                ticket.refresh_from_db()
                self.assertEqual(ticket.created_at, NOW)
                self.assertEqual(ticket.first_response_due_at, NOW + timedelta(minutes=minutes))

    def test_saving_later_does_not_move_the_due_date(self):
        ticket = self._create()
        with _frozen(NOW + timedelta(days=2)):
            ticket.title = "Renamed"
            ticket.save()
        ticket.refresh_from_db()
        self.assertEqual(ticket.first_response_due_at, NOW + timedelta(minutes=480))

    def test_changing_the_priority_recalculates_from_the_creation_time(self):
        ticket = self._create(priority=Ticket.Priority.MEDIUM)
        with _frozen(NOW + timedelta(days=3)):
            ticket.priority = Ticket.Priority.URGENT
            ticket.save(update_fields=["priority"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.first_response_due_at, NOW + timedelta(minutes=60))

    def test_saving_other_fields_only_leaves_the_due_date_alone(self):
        ticket = self._create()
        moved = NOW + timedelta(days=30)
        Ticket.objects.filter(pk=ticket.pk).update(first_response_due_at=moved)
        ticket.refresh_from_db()
        ticket.title = "Renamed"
        ticket.save(update_fields=["title"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.first_response_due_at, moved)

    def test_staff_changing_the_priority_through_the_api_moves_the_due_date(self):
        ticket = self._create(priority=Ticket.Priority.LOW)
        response = _client_for(self.agent).patch(
            f"{URL}{ticket.id}/", {"priority": Ticket.Priority.URGENT}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        due = parse_datetime(response.data["first_response_due_at"])
        self.assertEqual(due, NOW + timedelta(minutes=60))
        ticket.refresh_from_db()
        self.assertEqual(ticket.first_response_due_at, NOW + timedelta(minutes=60))

    def test_the_due_date_cannot_be_written_through_the_api(self):
        ticket = self._create()
        response = _client_for(self.agent).patch(
            f"{URL}{ticket.id}/", {"first_response_due_at": "2000-01-01T00:00:00Z"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.first_response_due_at, NOW + timedelta(minutes=480))

    def test_a_customer_ticket_gets_the_default_priority_target(self):
        response = _client_for(self.customer).post(
            URL, {"title": "t", "description": "d"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        ticket = Ticket.objects.get(pk=response.data["id"])
        expected = ticket.created_at + timedelta(minutes=480)
        self.assertLess(abs(ticket.first_response_due_at - expected), timedelta(seconds=1))

    def test_a_staff_ticket_gets_the_target_of_the_chosen_priority(self):
        response = _client_for(self.agent).post(
            URL,
            {"title": "t", "description": "d", "priority": Ticket.Priority.HIGH},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        ticket = Ticket.objects.get(pk=response.data["id"])
        expected = ticket.created_at + timedelta(minutes=240)
        self.assertLess(abs(ticket.first_response_due_at - expected), timedelta(seconds=1))

    def test_only_staff_see_the_due_date(self):
        ticket = self._create(customer=self.customer)
        owner = _client_for(self.customer).get(f"{URL}{ticket.id}/")
        staff = _client_for(self.agent).get(f"{URL}{ticket.id}/")
        self.assertNotIn("first_response_due_at", owner.data)
        self.assertIn("first_response_due_at", staff.data)
        listing = _client_for(self.customer).get(URL)
        self.assertNotIn("first_response_due_at", listing.data["results"][0])


class OverdueFilterTests(TestCase):
    def setUp(self):
        self.agent = AgentFactory()
        self.customer = UserFactory()

    def _ticket(self, due_in, **kwargs):
        ticket = TicketFactory(**kwargs)
        Ticket.objects.filter(pk=ticket.pk).update(first_response_due_at=NOW + due_in)
        return ticket

    def _overdue_ids(self, overdue=True):
        queryset = filter_overdue(Ticket.objects.all(), overdue=overdue, now=NOW)
        return set(queryset.values_list("pk", flat=True))

    def test_a_ticket_past_its_due_date_without_a_reply_is_overdue(self):
        ticket = self._ticket(PAST)
        self.assertEqual(self._overdue_ids(), {ticket.pk})

    def test_a_ticket_before_its_due_date_is_not_overdue(self):
        self._ticket(FUTURE)
        self.assertEqual(self._overdue_ids(), set())

    def test_the_moment_of_the_due_date_is_not_yet_overdue(self):
        self._ticket(timedelta(0))
        self.assertEqual(self._overdue_ids(), set())

    def test_one_second_after_the_due_date_is_overdue(self):
        ticket = self._ticket(timedelta(seconds=-1))
        self.assertEqual(self._overdue_ids(), {ticket.pk})

    def test_unfinished_statuses_can_be_overdue(self):
        statuses = (
            Ticket.Status.OPEN,
            Ticket.Status.IN_PROGRESS,
            Ticket.Status.WAITING_ON_CUSTOMER,
        )
        for status in statuses:
            with self.subTest(status=status):
                ticket = self._ticket(PAST, status=status)
                self.assertIn(ticket.pk, self._overdue_ids())

    def test_finished_tickets_are_never_overdue(self):
        for status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
            with self.subTest(status=status):
                ticket = self._ticket(PAST, status=status)
                self.assertNotIn(ticket.pk, self._overdue_ids())

    def test_a_public_staff_reply_ends_the_overdue_state(self):
        by_agent = self._ticket(PAST)
        by_admin = self._ticket(PAST)
        CommentFactory(ticket=by_agent, author=self.agent)
        CommentFactory(ticket=by_admin, author=AdminFactory())
        self.assertEqual(self._overdue_ids(), set())

    def test_replies_that_do_not_count_leave_the_ticket_overdue(self):
        ticket = self._ticket(PAST, customer=self.customer)
        CommentFactory(ticket=ticket, author=self.agent, is_internal=True)
        CommentFactory(ticket=ticket, author=self.customer)
        CommentFactory(ticket=ticket, author=None, visitor=None, kind=Comment.Kind.SYSTEM)
        self.assertEqual(self._overdue_ids(), {ticket.pk})

    def test_a_visitor_message_does_not_count_as_a_reply(self):
        ticket = self._ticket(PAST, from_visitor=True)
        CommentFactory(ticket=ticket, author=None, visitor=ticket.visitor)
        self.assertEqual(self._overdue_ids(), {ticket.pk})

    def test_a_ticket_without_a_due_date_is_never_overdue(self):
        ticket = TicketFactory()
        Ticket.objects.filter(pk=ticket.pk).update(first_response_due_at=None)
        self.assertEqual(self._overdue_ids(), set())
        self.assertEqual(self._overdue_ids(overdue=False), {ticket.pk})

    def test_the_negative_filter_returns_the_complement(self):
        late = self._ticket(PAST)
        on_time = self._ticket(FUTURE)
        answered = self._ticket(PAST)
        CommentFactory(ticket=answered, author=self.agent)
        self.assertEqual(self._overdue_ids(), {late.pk})
        self.assertEqual(self._overdue_ids(overdue=False), {on_time.pk, answered.pk})

    def test_deleted_tickets_are_not_returned(self):
        ticket = self._ticket(PAST)
        ticket.delete()
        self.assertEqual(self._overdue_ids(), set())

    def test_the_default_clock_is_the_current_time(self):
        ticket = TicketFactory()
        due = timezone.now() - timedelta(minutes=1)
        Ticket.objects.filter(pk=ticket.pk).update(first_response_due_at=due)
        result = filter_overdue(Ticket.objects.all())
        self.assertIn(ticket.pk, set(result.values_list("pk", flat=True)))

    def test_the_helper_returns_a_subquery_of_primary_keys(self):
        late = self._ticket(PAST)
        self._ticket(FUTURE)
        self.assertEqual(set(overdue_ticket_ids(NOW).values_list("pk", flat=True)), {late.pk})


class OverdueApiTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.staff = _client_for(self.agent)
        self.owner = _client_for(self.customer)
        self.late = self._ticket(timedelta(hours=-1), customer=self.customer)
        self.on_time = self._ticket(timedelta(hours=1), customer=self.customer)
        self.answered = self._ticket(timedelta(hours=-2), customer=self.customer)
        CommentFactory(ticket=self.answered, author=self.agent)

    def _ticket(self, due_in, **kwargs):
        ticket = TicketFactory(**kwargs)
        Ticket.objects.filter(pk=ticket.pk).update(first_response_due_at=timezone.now() + due_in)
        return ticket

    def _ids(self, client, query):
        response = client.get(f"{URL}{query}")
        self.assertEqual(response.status_code, 200)
        return {row["id"] for row in response.data["results"]}

    def test_staff_can_list_overdue_tickets(self):
        self.assertEqual(self._ids(self.staff, "?is_overdue=true"), {self.late.id})

    def test_staff_can_list_the_tickets_that_are_not_overdue(self):
        expected = {self.on_time.id, self.answered.id}
        self.assertEqual(self._ids(self.staff, "?is_overdue=false"), expected)

    def test_admins_can_use_the_filter(self):
        admin = _client_for(AdminFactory())
        self.assertEqual(self._ids(admin, "?is_overdue=true"), {self.late.id})

    def test_the_filter_combines_with_others(self):
        Ticket.objects.filter(pk=self.late.pk).update(status=Ticket.Status.IN_PROGRESS)
        self.assertEqual(
            self._ids(self.staff, "?is_overdue=true&status=in_progress"), {self.late.id}
        )
        self.assertEqual(self._ids(self.staff, "?is_overdue=true&status=open"), set())

    def test_customers_get_nothing_for_either_value(self):
        self.assertEqual(self._ids(self.owner, "?is_overdue=true"), set())
        self.assertEqual(self._ids(self.owner, "?is_overdue=false"), set())

    def test_a_staff_reply_removes_a_ticket_from_the_overdue_list(self):
        self.assertIn(self.late.id, self._ids(self.staff, "?is_overdue=true"))
        self.staff.post(f"{URL}{self.late.id}/comments/", {"body": "On it"}, format="json")
        self.assertEqual(self._ids(self.staff, "?is_overdue=true"), set())

    def test_unauthenticated_requests_are_rejected(self):
        self.assertEqual(APIClient().get(f"{URL}?is_overdue=true").status_code, 401)
