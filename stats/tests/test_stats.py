from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    TicketFactory,
    TicketRatingFactory,
    UserFactory,
)
from tickets.models import Ticket

URL = "/api/stats/"
RANGE = {"date_from": "2026-03-10", "date_to": "2026-03-12"}
STATS_KEYS = {
    "range",
    "queue_size",
    "open_chats_per_agent",
    "average_first_response_seconds",
    "average_resolution_seconds",
    "average_rating",
    "ratings_total",
    "tickets_total",
    "tickets_per_day",
    "tickets_per_channel",
}


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _utc(*args):
    return datetime(*args, tzinfo=UTC)


@contextmanager
def _frozen(moment):
    with patch("django.utils.timezone.now", return_value=moment):
        yield


def _create(created_at, first_response=None, resolution=None, **kwargs):
    if first_response is not None:
        kwargs["first_response_at"] = created_at + first_response
    if resolution is not None:
        kwargs["resolved_at"] = created_at + resolution
    with _frozen(created_at):
        return TicketFactory(**kwargs)


class StatsAccessTests(TestCase):
    def test_unauthenticated_requests_are_rejected(self):
        response = APIClient().get(URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "not_authenticated")

    def test_customers_are_forbidden(self):
        response = _client_for(UserFactory()).get(URL)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "permission_denied")

    def test_agents_and_admins_can_read_the_stats(self):
        for user in (AgentFactory(), AdminFactory()):
            with self.subTest(role=user.role):
                response = _client_for(user).get(URL)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(response.data), STATS_KEYS)

    def test_the_route_is_read_only(self):
        client = _client_for(AgentFactory())
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertEqual(getattr(client, method)(URL).status_code, 405)


class StatsFigureTests(TestCase):
    def setUp(self):
        self.client = _client_for(AgentFactory())
        day = timedelta(days=1)
        self.before = _create(
            _utc(2026, 3, 9, 20, 29),
            first_response=day,
            resolution=2 * day,
            status=Ticket.Status.RESOLVED,
        )
        self.first = _create(
            _utc(2026, 3, 9, 20, 30),
            first_response=timedelta(minutes=10),
            resolution=timedelta(hours=1),
            status=Ticket.Status.RESOLVED,
        )
        self.second = _create(
            _utc(2026, 3, 10, 21, 0),
            from_visitor=True,
            first_response=timedelta(minutes=20),
            resolution=timedelta(hours=3),
            status=Ticket.Status.RESOLVED,
        )
        self.third = _create(
            _utc(2026, 3, 12, 20, 29),
            from_visitor=True,
            channel=Ticket.Channel.OFFLINE_FORM,
        )
        self.after = _create(_utc(2026, 3, 12, 20, 30), first_response=day, resolution=day)
        hidden = _create(_utc(2026, 3, 11, 9, 0), first_response=day, resolution=day)
        hidden.delete()
        TicketRatingFactory(ticket=self.first, score=5)
        TicketRatingFactory(ticket=self.second, score=4)
        TicketRatingFactory(ticket=self.before, score=1)

    def _stats(self, **params):
        response = self.client.get(URL, params or RANGE)
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_the_range_is_echoed(self):
        self.assertEqual(dict(self._stats()["range"]), RANGE)

    def test_only_live_tickets_inside_the_range_are_counted(self):
        self.assertEqual(self._stats()["tickets_total"], 3)

    def test_the_range_edges_follow_tehran_midnight(self):
        stats = self._stats(date_from="2026-03-11", date_to="2026-03-11")
        self.assertEqual(stats["tickets_total"], 1)
        stats = self._stats(date_from="2026-03-09", date_to="2026-03-09")
        self.assertEqual(stats["tickets_total"], 1)
        stats = self._stats(date_from="2026-03-13", date_to="2026-03-13")
        self.assertEqual(stats["tickets_total"], 1)

    def test_tickets_per_day_covers_every_day_of_the_range(self):
        days = [dict(row) for row in self._stats()["tickets_per_day"]]
        self.assertEqual(
            days,
            [
                {"date": "2026-03-10", "count": 1},
                {"date": "2026-03-11", "count": 1},
                {"date": "2026-03-12", "count": 1},
            ],
        )

    def test_days_without_tickets_are_reported_as_zero(self):
        stats = self._stats(date_from="2026-03-06", date_to="2026-03-10")
        counts = [row["count"] for row in stats["tickets_per_day"]]
        self.assertEqual(counts, [0, 0, 0, 1, 1])

    def test_tickets_per_channel_lists_every_channel(self):
        channels = [dict(row) for row in self._stats()["tickets_per_channel"]]
        self.assertEqual(
            channels,
            [
                {"channel": "portal", "count": 1},
                {"channel": "chat", "count": 1},
                {"channel": "offline_form", "count": 1},
            ],
        )

    def test_average_times_use_only_tickets_that_have_them(self):
        stats = self._stats()
        self.assertEqual(stats["average_first_response_seconds"], 900.0)
        self.assertEqual(stats["average_resolution_seconds"], 7200.0)

    def test_averages_of_a_narrower_range(self):
        stats = self._stats(date_from="2026-03-11", date_to="2026-03-11")
        self.assertEqual(stats["average_first_response_seconds"], 1200.0)
        self.assertEqual(stats["average_resolution_seconds"], 10800.0)

    def test_ratings_cover_only_tickets_in_the_range(self):
        stats = self._stats()
        self.assertEqual(stats["ratings_total"], 2)
        self.assertEqual(stats["average_rating"], 4.5)
        narrow = self._stats(date_from="2026-03-11", date_to="2026-03-11")
        self.assertEqual((narrow["ratings_total"], narrow["average_rating"]), (1, 4.0))

    def test_an_average_rating_is_rounded_to_two_decimals(self):
        for score in (5, 4):
            ticket = _create(_utc(2026, 3, 11, 9, 0), status=Ticket.Status.RESOLVED)
            TicketRatingFactory(ticket=ticket, score=score)
        stats = self._stats(date_from="2026-03-11", date_to="2026-03-11")
        self.assertEqual(stats["ratings_total"], 3)
        self.assertEqual(stats["average_rating"], 4.33)


class StatsEmptyTests(TestCase):
    def test_a_range_without_tickets_reports_zeros_and_nulls(self):
        stats = _client_for(AgentFactory()).get(URL, RANGE).data
        self.assertEqual(stats["tickets_total"], 0)
        self.assertIsNone(stats["average_first_response_seconds"])
        self.assertIsNone(stats["average_resolution_seconds"])
        self.assertIsNone(stats["average_rating"])
        self.assertEqual(stats["ratings_total"], 0)
        self.assertEqual([row["count"] for row in stats["tickets_per_day"]], [0, 0, 0])
        self.assertEqual([row["count"] for row in stats["tickets_per_channel"]], [0, 0, 0])


class StatsQueueTests(TestCase):
    def test_the_queue_counts_live_unassigned_unfinished_tickets_regardless_of_the_range(self):
        agent = AgentFactory()
        old = _utc(2025, 1, 1, 9, 0)
        counted = [
            _create(old, status=Ticket.Status.OPEN),
            _create(old, status=Ticket.Status.IN_PROGRESS),
            _create(old, status=Ticket.Status.WAITING_ON_CUSTOMER),
        ]
        _create(old, assignee=agent)
        _create(old, status=Ticket.Status.RESOLVED)
        _create(old, status=Ticket.Status.CLOSED)
        _create(old).delete()
        stats = _client_for(agent).get(URL, RANGE).data
        self.assertEqual(stats["queue_size"], len(counted))
        self.assertEqual(stats["tickets_total"], 0)


class StatsAgentLoadTests(TestCase):
    def test_open_chats_are_counted_per_active_staff_member(self):
        requester = AgentFactory(first_name="Zed")
        ali = AgentFactory(first_name="Ali", last_name="Zand")
        bita = AgentFactory(first_name="Bita", last_name="Amini")
        cyrus = AdminFactory(first_name="Cyrus")
        AgentFactory(first_name="Gone", is_active=False)
        UserFactory(first_name="Customer")

        TicketFactory.create_batch(2, from_visitor=True, assignee=ali)
        TicketFactory(from_visitor=True, assignee=ali, status=Ticket.Status.RESOLVED)
        TicketFactory(from_visitor=True, assignee=ali, channel=Ticket.Channel.OFFLINE_FORM)
        TicketFactory(assignee=ali)
        TicketFactory(from_visitor=True, assignee=ali).delete()
        TicketFactory(from_visitor=True, assignee=bita, status=Ticket.Status.WAITING_ON_CUSTOMER)

        stats = _client_for(requester).get(URL).data
        rows = [
            (row["id"], row["name"], row["open_chats"]) for row in stats["open_chats_per_agent"]
        ]
        self.assertEqual(
            rows,
            [
                (ali.id, "Ali Zand", 2),
                (bita.id, "Bita Amini", 1),
                (cyrus.id, "Cyrus", 0),
                (requester.id, "Zed", 0),
            ],
        )


class StatsRangeValidationTests(TestCase):
    def setUp(self):
        self.client = _client_for(AgentFactory())

    def _assert_rejected(self, params, field):
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])

    def test_the_default_range_is_the_last_thirty_days(self):
        today = timezone.localdate()
        stats = self.client.get(URL).data
        self.assertEqual(stats["range"]["date_to"], str(today))
        self.assertEqual(stats["range"]["date_from"], str(today - timedelta(days=29)))
        self.assertEqual(len(stats["tickets_per_day"]), 30)

    def test_only_a_start_date_runs_until_today(self):
        start = timezone.localdate() - timedelta(days=4)
        stats = self.client.get(URL, {"date_from": str(start)}).data
        self.assertEqual(stats["range"]["date_to"], str(timezone.localdate()))
        self.assertEqual(len(stats["tickets_per_day"]), 5)

    def test_only_an_end_date_starts_twenty_nine_days_earlier(self):
        stats = self.client.get(URL, {"date_to": "2026-03-30"}).data
        self.assertEqual(stats["range"]["date_from"], "2026-03-01")
        self.assertEqual(len(stats["tickets_per_day"]), 30)

    def test_a_start_after_the_end_is_rejected(self):
        self._assert_rejected({"date_from": "2026-03-12", "date_to": "2026-03-10"}, "date_from")

    def test_a_range_of_366_days_is_accepted_and_367_is_not(self):
        ok = self.client.get(URL, {"date_from": "2025-01-01", "date_to": "2026-01-01"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(len(ok.data["tickets_per_day"]), 366)
        self._assert_rejected({"date_from": "2025-01-01", "date_to": "2026-01-02"}, "date_to")

    def test_malformed_dates_are_rejected(self):
        self._assert_rejected({"date_from": "2026-13-45"}, "date_from")
        self._assert_rejected({"date_to": "yesterday"}, "date_to")
