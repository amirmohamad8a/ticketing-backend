from datetime import UTC, datetime
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import UserEvent
from audit.queries import audit_page
from core.tests.factories import AdminFactory, AgentFactory, TicketEventFactory, UserFactory
from tickets.models import TicketEvent

URL = "/api/audit/"
ROW_KEYS = {
    "id",
    "kind",
    "ticket",
    "user",
    "actor",
    "actor_username",
    "field_changed",
    "old_value",
    "new_value",
    "created_at",
}
T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 3, 3, 9, 0, tzinfo=UTC)
T3 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _frozen(moment):
    return patch("django.utils.timezone.now", return_value=moment)


def _ticket_event(moment, **kwargs):
    with _frozen(moment):
        return TicketEventFactory(**kwargs)


def _user_event(
    moment,
    user=None,
    actor=None,
    field_changed="role",
    old_value="agent",
    new_value="admin",
):
    with _frozen(moment):
        return UserEvent.objects.create(
            user=user or AgentFactory(),
            actor=actor,
            field_changed=field_changed,
            old_value=old_value,
            new_value=new_value,
        )


def _paged(page_size):
    def wrapper(filters, cursor=None):
        return audit_page(filters, cursor, page_size=page_size)

    return wrapper


class AuditAccessTests(TestCase):
    def test_unauthenticated_requests_are_rejected(self):
        response = APIClient().get(URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "not_authenticated")

    def test_customers_and_agents_are_forbidden(self):
        for user in (UserFactory(), AgentFactory()):
            with self.subTest(role=user.role):
                response = _client_for(user).get(URL)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["error"]["code"], "permission_denied")

    def test_admins_can_read_the_log(self):
        self.assertEqual(_client_for(AdminFactory()).get(URL).status_code, 200)

    def test_the_route_is_read_only(self):
        client = _client_for(AdminFactory())
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertEqual(getattr(client, method)(URL).status_code, 405)


class AuditListTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)

    def _rows(self, **params):
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200)
        return response.data["results"]

    def test_an_empty_log_has_no_rows_and_no_next_page(self):
        response = self.client.get(URL)
        self.assertEqual(response.data["results"], [])
        self.assertIsNone(response.data["next"])

    def test_a_ticket_event_row_has_the_documented_shape(self):
        reviewer = AgentFactory(username="reviewer")
        event = _ticket_event(
            T1, actor=reviewer, field_changed="status", old_value="open", new_value="in_progress"
        )
        (row,) = self._rows()
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["id"], event.pk)
        self.assertEqual(row["kind"], "ticket")
        self.assertEqual(row["ticket"], event.ticket_id)
        self.assertIsNone(row["user"])
        self.assertEqual(row["actor"], reviewer.id)
        self.assertEqual(row["actor_username"], "reviewer")
        self.assertEqual(
            (row["field_changed"], row["old_value"], row["new_value"]),
            ("status", "open", "in_progress"),
        )

    def test_a_user_event_row_has_the_documented_shape(self):
        target = AgentFactory()
        event = _user_event(T1, user=target, actor=self.admin)
        (row,) = self._rows()
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual(row["id"], event.pk)
        self.assertEqual(row["kind"], "user")
        self.assertIsNone(row["ticket"])
        self.assertEqual(row["user"], target.id)
        self.assertEqual(row["actor"], self.admin.id)
        self.assertEqual(row["actor_username"], self.admin.username)

    def test_an_event_without_an_actor_has_no_actor_fields(self):
        _ticket_event(T1, actor=None)
        _user_event(T2, actor=None)
        for row in self._rows():
            self.assertIsNone(row["actor"])
            self.assertIsNone(row["actor_username"])

    def test_both_kinds_are_merged_newest_first(self):
        oldest = _ticket_event(T1)
        middle = _user_event(T2)
        newest = _ticket_event(T3)
        rows = self._rows()
        self.assertEqual(
            [(row["kind"], row["id"]) for row in rows],
            [("ticket", newest.pk), ("user", middle.pk), ("ticket", oldest.pk)],
        )

    def test_events_made_through_the_api_show_up(self):
        agent = AgentFactory(username="worker")
        ticket = TicketEventFactory().ticket
        _client_for(agent).patch(
            f"/api/tickets/{ticket.id}/", {"status": "in_progress"}, format="json"
        )
        created = self.client.post(
            "/api/users/", {"username": "fresh", "password": "S3cure-pass-91"}, format="json"
        )
        self.assertEqual(created.status_code, 201)
        status_row = next(
            row for row in self._rows(field_changed="status") if row["actor"] == agent.id
        )
        self.assertEqual(status_row["actor_username"], "worker")
        (created_row,) = self._rows(kind="user", field_changed="created")
        self.assertEqual(created_row["user"], created.data["id"])
        self.assertEqual(created_row["new_value"], "agent")
        self.assertEqual(created_row["actor"], self.admin.id)


class AuditFilterTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)
        self.alice = AgentFactory(username="alice")
        self.bob = AgentFactory(username="bob")
        self.alice_ticket = _ticket_event(T1, actor=self.alice, field_changed="status")
        self.bob_ticket = _ticket_event(T2, actor=self.bob, field_changed="assignee")
        self.alice_user = _user_event(T2, actor=self.alice, field_changed="role")
        self.bob_user = _user_event(T3, actor=self.bob, field_changed="is_active")

    def _keys(self, **params):
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200)
        return {(row["kind"], row["id"]) for row in response.data["results"]}

    def test_the_kind_filter(self):
        self.assertEqual(
            self._keys(kind="ticket"),
            {("ticket", self.alice_ticket.pk), ("ticket", self.bob_ticket.pk)},
        )
        self.assertEqual(
            self._keys(kind="user"),
            {("user", self.alice_user.pk), ("user", self.bob_user.pk)},
        )

    def test_the_actor_filter_spans_both_kinds(self):
        self.assertEqual(
            self._keys(actor=self.alice.id),
            {("ticket", self.alice_ticket.pk), ("user", self.alice_user.pk)},
        )

    def test_the_field_filter(self):
        self.assertEqual(self._keys(field_changed="assignee"), {("ticket", self.bob_ticket.pk)})
        self.assertEqual(self._keys(field_changed="is_active"), {("user", self.bob_user.pk)})
        self.assertEqual(self._keys(field_changed="nothing"), set())

    def test_filters_combine(self):
        self.assertEqual(self._keys(kind="user", actor=self.bob.id), {("user", self.bob_user.pk)})
        self.assertEqual(
            self._keys(kind="ticket", actor=self.bob.id, field_changed="status"), set()
        )

    def test_an_actor_without_events_returns_nothing(self):
        self.assertEqual(self._keys(actor=self.admin.id), set())


class AuditDateFilterTests(TestCase):
    def setUp(self):
        self.client = _client_for(AdminFactory())
        self.events = {
            "before": _ticket_event(datetime(2026, 3, 9, 20, 29, tzinfo=UTC)),
            "start": _ticket_event(datetime(2026, 3, 9, 20, 30, tzinfo=UTC)),
            "end": _ticket_event(datetime(2026, 3, 10, 20, 29, 59, tzinfo=UTC)),
            "after": _ticket_event(datetime(2026, 3, 10, 20, 30, tzinfo=UTC)),
        }

    def _names(self, **params):
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200)
        ids = {row["id"] for row in response.data["results"]}
        return {name for name, event in self.events.items() if event.pk in ids}

    def test_both_bounds_cover_the_whole_tehran_day(self):
        names = self._names(date_from="2026-03-10", date_to="2026-03-10")
        self.assertEqual(names, {"start", "end"})

    def test_only_a_start_date(self):
        self.assertEqual(self._names(date_from="2026-03-10"), {"start", "end", "after"})

    def test_only_an_end_date(self):
        self.assertEqual(self._names(date_to="2026-03-09"), {"before"})

    def test_dates_filter_user_events_too(self):
        user_event = _user_event(datetime(2026, 3, 10, 5, 0, tzinfo=UTC))
        response = self.client.get(URL, {"date_from": "2026-03-10", "date_to": "2026-03-10"})
        ids = {(row["kind"], row["id"]) for row in response.data["results"]}
        self.assertIn(("user", user_event.pk), ids)


class AuditValidationTests(TestCase):
    def setUp(self):
        self.client = _client_for(AdminFactory())

    def _assert_rejected(self, params, field):
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])

    def test_an_unknown_kind_is_rejected(self):
        self._assert_rejected({"kind": "comment"}, "kind")

    def test_invalid_actors_are_rejected(self):
        for value in ("0", "-1", "abc", "1.5"):
            with self.subTest(value=value):
                self._assert_rejected({"actor": value}, "actor")

    def test_invalid_dates_are_rejected(self):
        self._assert_rejected({"date_from": "2026-13-45"}, "date_from")
        self._assert_rejected({"date_to": "soon"}, "date_to")

    def test_a_start_after_the_end_is_rejected(self):
        self._assert_rejected({"date_from": "2026-03-12", "date_to": "2026-03-10"}, "date_from")

    def test_a_broken_cursor_is_rejected(self):
        self._assert_rejected({"cursor": "garbage"}, "cursor")
        self._assert_rejected({"cursor": "a" * 201}, "cursor")

    def test_an_overlong_field_name_is_rejected(self):
        self._assert_rejected({"field_changed": "x" * 51}, "field_changed")

    def test_unknown_parameters_are_ignored(self):
        self.assertEqual(self.client.get(URL, {"unknown": "1"}).status_code, 200)


class AuditPaginationTests(TestCase):
    def setUp(self):
        self.client = _client_for(AdminFactory())
        for _ in range(3):
            _ticket_event(T1)
            _user_event(T1)
        _ticket_event(T0)
        _ticket_event(T0)

    def _expected(self):
        rows = [("ticket", event.pk, event.created_at) for event in TicketEvent.objects.all()]
        rows += [("user", event.pk, event.created_at) for event in UserEvent.objects.all()]
        rows.sort(key=lambda row: (row[2], row[0], row[1]), reverse=True)
        return [(kind, pk) for kind, pk, _moment in rows]

    def _walk(self, page_size, query=""):
        pages = []
        url = f"{URL}{query}"
        with patch("audit.views.audit_page", _paged(page_size)):
            while url:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                pages.append([(row["kind"], row["id"]) for row in response.data["results"]])
                url = response.data["next"]
        return pages

    def test_every_page_size_walks_the_whole_log_in_order_without_repeats(self):
        expected = self._expected()
        self.assertEqual(len(expected), 8)
        for page_size in (1, 2, 3, 5, 8, 50):
            with self.subTest(page_size=page_size):
                pages = self._walk(page_size)
                self.assertTrue(all(len(page) <= page_size for page in pages))
                self.assertEqual([key for page in pages for key in page], expected)

    def test_the_last_page_has_no_next_link(self):
        self.assertEqual([len(page) for page in self._walk(3)], [3, 3, 2])
        self.assertEqual([len(page) for page in self._walk(8)], [8])

    def test_the_next_link_keeps_the_filters(self):
        pages = self._walk(2, "?kind=ticket")
        flat = [key for page in pages for key in page]
        self.assertEqual(len(flat), 5)
        self.assertTrue(all(kind == "ticket" for kind, _pk in flat))
        with patch("audit.views.audit_page", _paged(2)):
            response = self.client.get(f"{URL}?kind=ticket")
        self.assertIn("kind=ticket", response.data["next"])
        self.assertIn("cursor=", response.data["next"])

    def test_the_default_page_size_is_fifty(self):
        for _ in range(60):
            _ticket_event(T2)
        response = self.client.get(URL)
        self.assertEqual(len(response.data["results"]), 50)
        self.assertIsNotNone(response.data["next"])


class AuditPageServiceTests(TestCase):
    def test_a_page_reports_the_cursor_of_its_last_row(self):
        for moment in (T1, T2, T3):
            _ticket_event(moment)
        rows, cursor = audit_page({}, page_size=2)
        self.assertEqual(len(rows), 2)
        self.assertIsNotNone(cursor)
        rest, end = audit_page({}, _decoded(cursor), page_size=2)
        self.assertEqual(len(rest), 1)
        self.assertIsNone(end)

    def test_a_log_that_fits_one_page_has_no_cursor(self):
        _ticket_event(T1)
        rows, cursor = audit_page({}, page_size=5)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(cursor)


def _decoded(cursor):
    from audit.cursors import decode_cursor

    return decode_cursor(cursor)


class AuditSecretTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)

    def test_a_password_reset_row_holds_no_secret(self):
        target = AgentFactory()
        secret = "Reset-pass-6074"
        reset = self.client.patch(f"/api/users/{target.id}/", {"password": secret}, format="json")
        self.assertEqual(reset.status_code, 200)
        response = self.client.get(URL, {"field_changed": "password"})
        (row,) = response.data["results"]
        self.assertEqual(row["kind"], "user")
        self.assertEqual(row["user"], target.id)
        self.assertEqual(row["actor"], self.admin.id)
        self.assertEqual((row["old_value"], row["new_value"]), ("", ""))
        self.assertNotIn(secret, response.content.decode())

    def test_values_stored_under_the_password_field_are_never_returned(self):
        _user_event(T1, field_changed="password", old_value="old-secret", new_value="new-secret")
        response = self.client.get(URL)
        (row,) = response.data["results"]
        self.assertEqual((row["old_value"], row["new_value"]), ("", ""))
        body = response.content.decode()
        self.assertNotIn("old-secret", body)
        self.assertNotIn("new-secret", body)

    def test_other_fields_keep_their_values(self):
        _user_event(T1, field_changed="role", old_value="agent", new_value="admin")
        (row,) = self.client.get(URL).data["results"]
        self.assertEqual((row["old_value"], row["new_value"]), ("agent", "admin"))


class AuditQueryCountTests(TestCase):
    def _count(self, client):
        with CaptureQueriesContext(connection) as queries:
            response = client.get(URL)
        self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_the_number_of_queries_does_not_grow_with_the_number_of_rows(self):
        client = _client_for(AdminFactory())
        for _ in range(2):
            _ticket_event(T1)
            _user_event(T1, actor=AgentFactory())
        few = self._count(client)
        for _ in range(10):
            _ticket_event(T2)
            _user_event(T2, actor=AgentFactory())
        self.assertEqual(self._count(client), few)
