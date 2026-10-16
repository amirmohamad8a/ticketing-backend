import csv
import io
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests import read_streaming_body
from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    CommentFactory,
    TagFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)
from tickets import export
from tickets.models import Ticket

URL = "/api/tickets/export/"
CREATED = datetime(2026, 3, 10, 20, 30, tzinfo=UTC)
SLA_MINUTES = {"low": 1440, "medium": 480, "high": 240, "urgent": 60}
EXPECTED_HEADER = [
    "id",
    "title",
    "status",
    "priority",
    "channel",
    "customer",
    "visitor",
    "assignee",
    "tags",
    "created_at",
    "first_response_due_at",
    "first_response_at",
    "resolved_at",
    "updated_at",
]


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _body(response):
    return read_streaming_body(response)


def _table(response):
    text = _body(response).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _frozen(moment):
    return patch("django.utils.timezone.now", return_value=moment)


class ExportAccessTests(TestCase):
    def test_unauthenticated_requests_are_rejected(self):
        response = APIClient().get(URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "not_authenticated")

    def test_customers_are_forbidden(self):
        response = _client_for(UserFactory()).get(URL)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "permission_denied")

    def test_agents_and_admins_can_export(self):
        for user in (AgentFactory(), AdminFactory()):
            with self.subTest(role=user.role):
                response = _client_for(user).get(URL)
                self.assertEqual(response.status_code, 200)
                _body(response)

    def test_only_get_is_allowed(self):
        response = _client_for(AgentFactory()).post(URL)
        self.assertEqual(response.status_code, 405)

    def test_the_export_has_its_own_rate_limit(self):
        cache.clear()
        self.addCleanup(cache.clear)
        client = _client_for(AgentFactory())
        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"export": "2/min"}):
            statuses = [client.get(URL).status_code for _ in range(3)]
        self.assertEqual(statuses, [200, 200, 429])


@override_settings(SLA_FIRST_RESPONSE_MINUTES=SLA_MINUTES)
class ExportContentTests(TestCase):
    def setUp(self):
        self.agent = AgentFactory(username="sara.agent")
        self.client = _client_for(self.agent)

    def test_the_response_is_a_forced_utf8_download_with_a_byte_order_mark(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertRegex(
            response["Content-Disposition"], r'^attachment; filename="tickets-\d{8}-\d{6}\.csv"$'
        )
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertTrue(_body(response).startswith(export.UTF8_BOM))

    def test_an_empty_export_holds_only_the_header(self):
        response = self.client.get(URL)
        text = _body(response).decode("utf-8-sig")
        self.assertEqual(list(csv.reader(io.StringIO(text, newline=""))), [EXPECTED_HEADER])
        self.assertEqual(export.HEADER, EXPECTED_HEADER)

    def test_a_row_describes_the_ticket(self):
        customer = UserFactory(username="alice")
        tag = TagFactory(name="billing")
        with _frozen(CREATED):
            ticket = TicketFactory(
                customer=customer,
                title="Printer broken",
                priority=Ticket.Priority.URGENT,
                assignee=self.agent,
                tags=[tag],
            )
        (row,) = _table(self.client.get(URL))
        self.assertEqual(
            row,
            {
                "id": str(ticket.id),
                "title": "Printer broken",
                "status": "open",
                "priority": "urgent",
                "channel": "portal",
                "customer": "alice",
                "visitor": "",
                "assignee": "sara.agent",
                "tags": "billing",
                "created_at": "2026-03-11T00:00:00+03:30",
                "first_response_due_at": "2026-03-11T01:00:00+03:30",
                "first_response_at": "",
                "resolved_at": "",
                "updated_at": "2026-03-11T00:00:00+03:30",
            },
        )

    def test_response_and_resolution_times_are_exported(self):
        with _frozen(CREATED):
            TicketFactory(
                status=Ticket.Status.RESOLVED,
                first_response_at=CREATED + timedelta(minutes=10),
                resolved_at=CREATED + timedelta(hours=1),
            )
        (row,) = _table(self.client.get(URL))
        self.assertEqual(row["first_response_at"], "2026-03-11T00:10:00+03:30")
        self.assertEqual(row["resolved_at"], "2026-03-11T01:00:00+03:30")

    def test_a_visitor_ticket_shows_the_visitor_and_no_customer(self):
        visitor = VisitorFactory(name="Sara")
        TicketFactory(from_visitor=True, visitor=visitor)
        (row,) = _table(self.client.get(URL))
        self.assertEqual((row["customer"], row["visitor"], row["channel"]), ("", "Sara", "chat"))

    def test_several_tags_share_one_cell_in_name_order(self):
        TicketFactory(tags=[TagFactory(name="bravo"), TagFactory(name="alpha")])
        (row,) = _table(self.client.get(URL))
        self.assertEqual(row["tags"], "alpha; bravo")

    def test_rows_are_listed_newest_first_and_deleted_tickets_are_left_out(self):
        tickets = TicketFactory.create_batch(3)
        hidden = TicketFactory()
        hidden.delete()
        ids = [int(row["id"]) for row in _table(self.client.get(URL))]
        self.assertEqual(ids, sorted((ticket.id for ticket in tickets), reverse=True))
        self.assertNotIn(hidden.id, ids)

    def test_text_that_looks_like_a_formula_is_neutralised(self):
        TicketFactory(
            title='=HYPERLINK("http://evil.example")',
            assignee=AgentFactory(username="+risky"),
            tags=[TagFactory(name="=sum")],
        )
        TicketFactory(title="-5 items")
        TicketFactory(title="@mention")
        TicketFactory(from_visitor=True, visitor=VisitorFactory(name="@visitor"))
        TicketFactory(title="Safe title")
        rows = {row["title"]: row for row in _table(self.client.get(URL))}
        self.assertEqual(rows['\'=HYPERLINK("http://evil.example")']["assignee"], "'+risky")
        self.assertEqual(rows['\'=HYPERLINK("http://evil.example")']["tags"], "'=sum")
        self.assertIn("'-5 items", rows)
        self.assertIn("'@mention", rows)
        self.assertIn("Safe title", rows)
        visitors = {row["visitor"] for row in rows.values()}
        self.assertIn("'@visitor", visitors)

    def test_commas_quotes_and_line_breaks_survive_a_round_trip(self):
        title = 'He said "hi", then\nleft'
        TicketFactory(title=title)
        (row,) = _table(self.client.get(URL))
        self.assertEqual(row["title"], title)

    def test_persian_text_is_intact(self):
        TicketFactory(title="گزارش مشکل چاپگر", tags=[TagFactory(name="پرداخت")])
        (row,) = _table(self.client.get(URL))
        self.assertEqual(row["title"], "گزارش مشکل چاپگر")
        self.assertEqual(row["tags"], "پرداخت")

    def test_the_current_filters_are_respected(self):
        customer = UserFactory()
        tag = TagFactory(name="mobile")
        wanted = TicketFactory(
            customer=customer,
            title="Printer jammed",
            status=Ticket.Status.IN_PROGRESS,
            priority=Ticket.Priority.HIGH,
            assignee=self.agent,
            tags=[tag],
        )
        TicketFactory(title="Printer jammed too")
        TicketFactory(title="Keyboard", status=Ticket.Status.IN_PROGRESS)
        queries = (
            "?status=in_progress&priority=high",
            "?search=jammed&status=in_progress",
            "?assignee=me",
            f"?tag={tag.id}",
        )
        for query in queries:
            with self.subTest(query=query):
                ids = [int(row["id"]) for row in _table(self.client.get(f"{URL}{query}"))]
                self.assertEqual(ids, [wanted.id])

    def test_the_overdue_filter_applies(self):
        late = TicketFactory()
        Ticket.objects.filter(pk=late.pk).update(
            first_response_due_at=datetime.now(UTC) - timedelta(hours=1)
        )
        answered = TicketFactory()
        Ticket.objects.filter(pk=answered.pk).update(
            first_response_due_at=datetime.now(UTC) - timedelta(hours=1)
        )
        CommentFactory(ticket=answered, author=self.agent)
        ids = [int(row["id"]) for row in _table(self.client.get(f"{URL}?is_overdue=true"))]
        self.assertEqual(ids, [late.id])

    def test_an_invalid_filter_is_a_validation_error(self):
        response = self.client.get(f"{URL}?status=bogus")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")

    def test_the_export_ignores_pagination(self):
        TicketFactory.create_batch(25)
        self.assertEqual(len(_table(self.client.get(URL))), 25)


class ExportBatchingTests(TestCase):
    def setUp(self):
        self.client = _client_for(AgentFactory())

    def _export(self, batch_size):
        original = export._fetch_batch
        calls = []

        def counting(queryset, before_id):
            calls.append(before_id)
            return original(queryset, before_id)

        with patch.object(export, "EXPORT_BATCH_SIZE", batch_size):
            with patch.object(export, "_fetch_batch", counting):
                rows = _table(self.client.get(URL))
        return rows, calls

    def test_rows_are_streamed_in_batches_and_nothing_is_lost(self):
        tickets = TicketFactory.create_batch(5)
        rows, calls = self._export(2)
        expected = sorted((ticket.id for ticket in tickets), reverse=True)
        self.assertEqual([int(row["id"]) for row in rows], expected)
        self.assertEqual(len(calls), 3)
        self.assertIsNone(calls[0])
        self.assertEqual(calls[1], expected[1])
        self.assertEqual(calls[2], expected[3])

    def test_a_short_last_batch_ends_the_stream_without_another_query(self):
        TicketFactory.create_batch(3)
        rows, calls = self._export(500)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(calls), 1)

    def test_a_full_last_batch_needs_one_more_empty_query(self):
        TicketFactory.create_batch(4)
        rows, calls = self._export(2)
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(calls), 3)

    def test_an_empty_export_runs_a_single_query(self):
        rows, calls = self._export(2)
        self.assertEqual(rows, [])
        self.assertEqual(len(calls), 1)
