from django.test import TestCase

from rest_framework.test import APIClient

from chat.models import Visitor
from core.tests.factories import SiteFactory
from core.tests.security_support import ORIGIN, make_world, visitor_client
from tickets.models import Comment, Ticket

SPOOFED_ORIGINS = [
    "https://example.com.evil.com",
    "https://evil.com/https://example.com",
    "https://example.com@evil.com",
    "https://example.com:443@evil.com",
    "http://example.com",
    "https://example.com:8443",
    "https://sub.example.com",
    "https://example.org",
    "https://example.com/",
    "https://example.com.",
    "https://exa mple.com",
    "//example.com",
    "example.com",
    "null",
    "*",
    "",
]


class WidgetOriginSpoofingTests(TestCase):
    def setUp(self):
        self.world = make_world()
        self.messages_url = f"/api/widget/conversations/{self.world.ticket_a.id}/messages/"

    def test_the_config_refuses_every_spoofed_origin(self):
        for origin in SPOOFED_ORIGINS:
            with self.subTest(origin=origin):
                response = APIClient().get(
                    "/api/widget/config/", {"key": self.world.site.key}, HTTP_ORIGIN=origin
                )
                self.assertEqual(response.status_code, 403)

    def test_starting_a_conversation_from_a_spoofed_origin_creates_nothing(self):
        visitors = Visitor.objects.count()
        tickets = Ticket.all_objects.count()
        for origin in SPOOFED_ORIGINS:
            with self.subTest(origin=origin):
                response = APIClient().post(
                    "/api/widget/conversations/",
                    {"site_key": self.world.site.key, "body": "hello"},
                    format="json",
                    HTTP_ORIGIN=origin,
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(Visitor.objects.count(), visitors)
        self.assertEqual(Ticket.all_objects.count(), tickets)

    def test_a_valid_token_from_a_spoofed_origin_reads_and_writes_nothing(self):
        before = Comment.objects.count()
        for origin in SPOOFED_ORIGINS:
            with self.subTest(origin=origin):
                client = visitor_client(self.world.visitor_a, origin=origin)
                self.assertEqual(client.get(self.messages_url).status_code, 403)
                post = client.post(self.messages_url, {"body": "hi"}, format="json")
                self.assertEqual(post.status_code, 403)
        self.assertEqual(Comment.objects.count(), before)

    def test_a_referer_does_not_replace_the_origin_header(self):
        client = visitor_client(self.world.visitor_a, origin=None)
        response = client.get(self.messages_url, HTTP_REFERER=f"{ORIGIN}/page")
        self.assertEqual(response.status_code, 403)
        config = APIClient().get(
            "/api/widget/config/", {"key": self.world.site.key}, HTTP_REFERER=f"{ORIGIN}/page"
        )
        self.assertEqual(config.status_code, 403)

    def test_an_origin_of_another_site_does_not_open_this_one(self):
        other = SiteFactory(allowed_origins=["https://other.example"])
        client = visitor_client(self.world.visitor_a, origin="https://other.example")
        self.assertEqual(client.get(self.messages_url).status_code, 403)
        config = APIClient().get(
            "/api/widget/config/", {"key": self.world.site.key}, HTTP_ORIGIN="https://other.example"
        )
        self.assertEqual(config.status_code, 403)
        self.assertEqual(other.allowed_origins, ["https://other.example"])

    def test_a_token_cannot_borrow_the_origin_list_of_another_site(self):
        other = SiteFactory(allowed_origins=["https://other.example"])
        before = Comment.objects.count()
        client = visitor_client(self.world.visitor_a, origin="https://other.example")
        response = client.post(
            "/api/widget/conversations/",
            {"site_key": other.key, "body": "hello"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Comment.objects.count(), before)

    def test_a_site_without_allowed_origins_refuses_everyone(self):
        site = SiteFactory(allowed_origins=[])
        response = APIClient().get("/api/widget/config/", {"key": site.key}, HTTP_ORIGIN=ORIGIN)
        self.assertEqual(response.status_code, 403)


class CorsAndCachingTests(TestCase):
    def test_staff_routes_never_grant_cors_to_a_foreign_origin(self):
        response = APIClient().get("/api/auth/me/", HTTP_ORIGIN="https://evil.example")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)

    def test_widget_responses_never_allow_credentials(self):
        world = make_world()
        response = APIClient().get(
            "/api/widget/config/", {"key": world.site.key}, HTTP_ORIGIN=ORIGIN
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)

    def test_widget_responses_are_never_cached(self):
        world = make_world()
        url = f"/api/widget/conversations/{world.ticket_a.id}/messages/"
        ok = visitor_client(world.visitor_a).get(url)
        spoofed = visitor_client(world.visitor_a, origin="https://evil.example").get(url)
        anonymous = APIClient().get(url)
        self.assertEqual(
            (ok.status_code, spoofed.status_code, anonymous.status_code), (200, 403, 401)
        )
        for response in (ok, spoofed, anonymous):
            self.assertEqual(response["Cache-Control"], "private, no-store")
