from unittest.mock import patch

from django.test import TestCase, override_settings

from rest_framework.test import APIClient

from core.health import clear_cached_checks
from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    CommentFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)
from core.tests.security_support import ORIGIN, client_for, make_world, visitor_client
from tickets.models import Comment

METRICS_TOKEN = "s3cret-metrics-token"


class MetricsAccessTests(TestCase):
    @override_settings(METRICS_TOKEN=METRICS_TOKEN)
    def test_anything_but_the_exact_token_is_refused(self):
        admin_token = client_for(AdminFactory())._credentials["HTTP_AUTHORIZATION"]
        headers = [
            {},
            {"HTTP_AUTHORIZATION": "Bearer wrong"},
            {"HTTP_AUTHORIZATION": f"Basic {METRICS_TOKEN}"},
            {"HTTP_AUTHORIZATION": METRICS_TOKEN},
            {"HTTP_AUTHORIZATION": f"Bearer {METRICS_TOKEN}-extra"},
            {"HTTP_AUTHORIZATION": f"Bearer {METRICS_TOKEN[:-1]}"},
            {"HTTP_AUTHORIZATION": f"Bearer {METRICS_TOKEN} extra"},
            {"HTTP_AUTHORIZATION": admin_token},
        ]
        for extra in headers:
            with self.subTest(extra=extra):
                response = self.client.get("/metrics/", **extra)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response["WWW-Authenticate"], "Bearer")

    @override_settings(METRICS_TOKEN=METRICS_TOKEN)
    def test_the_token_is_not_accepted_in_the_query_string(self):
        response = self.client.get(f"/metrics/?token={METRICS_TOKEN}")
        self.assertEqual(response.status_code, 401)

    @override_settings(METRICS_TOKEN=METRICS_TOKEN)
    def test_the_right_token_gets_uncacheable_metrics_that_do_not_contain_it(self):
        response = self.client.get("/metrics/", HTTP_AUTHORIZATION=f"Bearer {METRICS_TOKEN}")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("ticketing_queue_size", body)
        self.assertNotIn(METRICS_TOKEN, body)
        self.assertIn("no-store", response["Cache-Control"])

    @override_settings(METRICS_TOKEN=METRICS_TOKEN)
    def test_only_read_methods_are_allowed(self):
        response = self.client.post("/metrics/", HTTP_AUTHORIZATION=f"Bearer {METRICS_TOKEN}")
        self.assertEqual(response.status_code, 405)

    @override_settings(METRICS_TOKEN="")
    def test_the_endpoint_does_not_exist_when_no_token_is_configured(self):
        for extra in ({}, {"HTTP_AUTHORIZATION": "Bearer "}, {"HTTP_AUTHORIZATION": "Bearer x"}):
            with self.subTest(extra=extra):
                self.assertEqual(self.client.get("/metrics/", **extra).status_code, 404)


class ReadinessLeakTests(TestCase):
    def setUp(self):
        clear_cached_checks()
        self.addCleanup(clear_cached_checks)

    def test_a_failing_check_never_exposes_its_error(self):
        def failing():
            raise RuntimeError("postgres://user:hunter2@db.internal:5432/ticketing")

        with patch("core.health.CHECKS", (("database", failing),)):
            with self.assertLogs("core.health", level="WARNING"):
                response = self.client.get("/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(), {"status": "unavailable", "checks": {"database": "error"}}
        )
        self.assertNotIn("hunter2", response.content.decode())

    def test_ready_warns_when_forwarded_for_is_present_but_ignored(self):
        with patch("core.health.CHECKS", ()), override_settings(NUM_PROXIES=0):
            with self.assertLogs("core.views", level="WARNING"):
                response = self.client.get("/ready/", HTTP_X_FORWARDED_FOR="203.0.113.9")
        self.assertEqual(response.status_code, 200)
        self.assertIn("NUM_PROXIES", response.json()["warnings"][0])


class AccountEnumerationTests(TestCase):
    def test_login_failures_look_identical_for_every_cause(self):
        active = UserFactory(password="Right-pass-4821")
        inactive = UserFactory(password="Right-pass-4821", is_active=False)
        client = APIClient()
        attempts = [
            {"username": "no-such-user", "password": "Right-pass-4821"},
            {"username": active.username, "password": "Wrong-pass-0000"},
            {"username": inactive.username, "password": "Right-pass-4821"},
        ]
        responses = [client.post("/api/token/", attempt) for attempt in attempts]
        for response in responses:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.data, responses[0].data)


class SensitiveDataExposureTests(TestCase):
    def test_password_hashes_never_appear_in_any_user_payload(self):
        admin = AdminFactory()
        target = AgentFactory()
        customer = UserFactory()
        client = client_for(admin)
        urls = [
            "/api/users/",
            f"/api/users/{target.id}/",
            "/api/auth/me/",
            "/api/agents/",
            "/api/agents/online/",
            "/api/audit/",
        ]
        for url in urls:
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                body = response.content.decode()
                for user in (admin, target, customer):
                    self.assertNotIn(user.password, body)

    def test_the_widget_never_reveals_staff_account_details(self):
        world = make_world()
        agent = AgentFactory(
            username="hidden_login_name",
            first_name="Sara",
            last_name="Ahmadi",
            phone="09121112233",
        )
        CommentFactory(ticket=world.ticket_a, author=agent, body="reply")
        response = visitor_client(world.visitor_a).get(
            f"/api/widget/conversations/{world.ticket_a.id}/messages/"
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Sara Ahmadi", body)
        for secret in ("hidden_login_name", "09121112233", "@example.com", "reply@"):
            self.assertNotIn(secret, body)

    def test_the_public_widget_config_exposes_only_display_settings(self):
        world = make_world()
        response = APIClient().get(
            "/api/widget/config/", {"key": world.site.key}, HTTP_ORIGIN=ORIGIN
        )
        self.assertEqual(
            set(response.data),
            {
                "name",
                "greeting",
                "primary_color",
                "position",
                "offline_timeout_minutes",
                "require_name",
                "require_contact",
                "agents_available",
            },
        )

    def test_starting_a_conversation_exposes_no_staff_or_owner_fields(self):
        world = make_world()
        response = APIClient().post(
            "/api/widget/conversations/",
            {"site_key": world.site.key, "body": "hello"},
            format="json",
            HTTP_ORIGIN=ORIGIN,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            set(response.data), {"token", "conversation", "message", "agents_available"}
        )
        self.assertEqual(
            set(response.data["conversation"]), {"id", "status", "channel", "created_at"}
        )


class MassAssignmentTests(TestCase):
    def test_a_customer_cannot_forge_the_sender_kind_or_ticket_of_a_comment(self):
        owner = UserFactory()
        admin = AdminFactory()
        visitor = VisitorFactory()
        ticket = TicketFactory(customer=owner)
        other_ticket = TicketFactory()
        response = client_for(owner).post(
            f"/api/tickets/{ticket.id}/comments/",
            {
                "body": "hello",
                "author": admin.id,
                "visitor": visitor.id,
                "kind": "system",
                "ticket": other_ticket.id,
                "is_internal": True,
                "id": 999999,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        comment = Comment.objects.get(pk=response.data["id"])
        self.assertNotEqual(comment.pk, 999999)
        self.assertEqual(comment.author, owner)
        self.assertIsNone(comment.visitor)
        self.assertEqual(comment.kind, Comment.Kind.MESSAGE)
        self.assertEqual(comment.ticket, ticket)
        self.assertFalse(comment.is_internal)

    def test_an_agent_cannot_post_in_the_name_of_someone_else(self):
        customer = UserFactory()
        agent = AgentFactory()
        ticket = TicketFactory(customer=customer)
        response = client_for(agent).post(
            f"/api/tickets/{ticket.id}/comments/",
            {"body": "hello", "author": customer.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Comment.objects.get(pk=response.data["id"]).author, agent)

    def test_a_visitor_cannot_forge_a_staff_note_or_another_visitor(self):
        world = make_world()
        response = visitor_client(world.visitor_a).post(
            f"/api/widget/conversations/{world.ticket_a.id}/messages/",
            {
                "body": "hello",
                "is_internal": True,
                "kind": "system",
                "author": world.agent.id,
                "visitor": world.visitor_b.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        comment = Comment.objects.get(pk=response.data["id"])
        self.assertEqual(comment.visitor, world.visitor_a)
        self.assertIsNone(comment.author)
        self.assertEqual(comment.kind, Comment.Kind.MESSAGE)
        self.assertFalse(comment.is_internal)

    def test_a_message_id_cannot_be_replayed_to_overwrite_or_read_another_senders_message(self):
        customer = UserFactory()
        agent = AgentFactory()
        ticket = TicketFactory(customer=customer)
        other_ticket = TicketFactory(customer=customer)
        owner_client = client_for(customer)
        url = f"/api/tickets/{ticket.id}/comments/"
        first = owner_client.post(
            url, {"body": "original", "client_msg_id": "shared-id"}, format="json"
        )
        self.assertEqual(first.status_code, 201)
        replay = client_for(agent).post(
            url, {"body": "overwritten", "client_msg_id": "shared-id"}, format="json"
        )
        self.assertEqual(replay.status_code, 400)
        self.assertIn("client_msg_id", replay.data["error"]["details"])
        stored = Comment.objects.filter(client_msg_id="shared-id", ticket=ticket)
        self.assertEqual([comment.body for comment in stored], ["original"])
        elsewhere = owner_client.post(
            f"/api/tickets/{other_ticket.id}/comments/",
            {"body": "elsewhere", "client_msg_id": "shared-id"},
            format="json",
        )
        self.assertEqual(elsewhere.status_code, 201)


class QueryInjectionTests(TestCase):
    def setUp(self):
        self.agent = AgentFactory()
        self.client = client_for(self.agent)
        self.ticket = TicketFactory(title="Printer on fire")

    def test_search_terms_are_data_never_sql_or_wildcards(self):
        terms = [
            "' OR '1'='1",
            "'; DROP TABLE tickets_ticket; --",
            '"unbalanced',
            "a & | ! ( ) <-> :*",
            "\\",
            "%",
            "_",
        ]
        for term in terms:
            with self.subTest(term=term):
                response = self.client.get("/api/tickets/", {"search": term})
                self.assertEqual(response.status_code, 200)
        for wildcard in ("%", "_"):
            response = self.client.get("/api/tickets/", {"search": wildcard})
            self.assertEqual(response.data["results"], [])
        found = self.client.get("/api/tickets/", {"search": "printer"})
        self.assertEqual([row["id"] for row in found.data["results"]], [self.ticket.id])

    def test_numeric_and_choice_filters_reject_injected_values(self):
        cases = {
            "assignee": "1 OR 1=1",
            "tag": "1;DROP TABLE tickets_ticket",
            "status": "open' OR '1'='1",
            "priority": "high' --",
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                response = self.client.get("/api/tickets/", {name: value})
                self.assertEqual(response.status_code, 400)
                self.assertIn(name, response.data["error"]["details"])
