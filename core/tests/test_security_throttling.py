from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from core.tests.factories import SiteFactory, UserFactory, VisitorFactory
from core.tests.security_support import (
    ORIGIN,
    client_for,
    make_world,
    upload,
    use_temp_media,
    visitor_client,
)
from tickets.models import Comment, Ticket

START_URL = "/api/widget/conversations/"


def _rates(**rates):
    return patch.dict(SimpleRateThrottle.THROTTLE_RATES, rates)


class ThrottleTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)


class LoginBruteForceTests(ThrottleTestCase):
    def _login(self, username="ghost", **extra):
        payload = {"username": username, "password": "wrong-pass-1"}
        return APIClient().post("/api/token/", payload, **extra).status_code

    def test_guessing_many_usernames_from_one_address_shares_one_budget(self):
        with _rates(login="2/min"):
            statuses = [self._login(f"ghost{index}") for index in range(4)]
        self.assertEqual(statuses, [401, 401, 429, 429])

    def test_only_the_trusted_proxy_hop_identifies_the_client(self):
        config = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
        with override_settings(REST_FRAMEWORK=config), _rates(login="1/min"):
            first = self._login(HTTP_X_FORWARDED_FOR="10.0.0.1, 5.5.5.5")
            spoofed = self._login(HTTP_X_FORWARDED_FOR="10.0.0.2, 5.5.5.5")
            other = self._login(HTTP_X_FORWARDED_FOR="10.0.0.1, 6.6.6.6")
        self.assertEqual((first, spoofed, other), (401, 429, 401))


class WidgetThrottleTests(ThrottleTestCase):
    def setUp(self):
        super().setUp()
        use_temp_media(self)

    def test_conversation_starts_are_limited_per_address(self):
        site = SiteFactory(allowed_origins=[ORIGIN])
        payload = {"site_key": site.key, "body": "hello"}
        client = APIClient()
        with _rates(widget_start="2/hour"):
            statuses = [
                client.post(START_URL, payload, format="json", HTTP_ORIGIN=ORIGIN).status_code
                for _attempt in range(3)
            ]
            other = client.post(
                START_URL, payload, format="json", HTTP_ORIGIN=ORIGIN, REMOTE_ADDR="10.9.9.9"
            )
        self.assertEqual(statuses, [201, 201, 429])
        self.assertEqual(other.status_code, 201)
        self.assertEqual(Ticket.objects.count(), 3)

    def test_each_visitor_has_a_separate_budget(self):
        world = make_world()
        first = visitor_client(world.visitor_a)
        second = visitor_client(world.visitor_b)
        url_a = f"/api/widget/conversations/{world.ticket_a.id}/messages/"
        url_b = f"/api/widget/conversations/{world.ticket_b.id}/messages/"
        with _rates(widget_visitor="2/min"):
            statuses = [first.get(url_a).status_code for _attempt in range(3)]
            blocked = first.get(url_a)
            other = second.get(url_b)
        self.assertEqual(statuses, [200, 200, 429])
        self.assertEqual(blocked.data["error"]["code"], "throttled")
        self.assertGreater(int(blocked["Retry-After"]), 0)
        self.assertEqual(other.status_code, 200)

    def test_the_address_budget_is_shared_by_every_widget_route(self):
        world = make_world()
        client = visitor_client(world.visitor_a)
        config = {"key": world.site.key}
        url = f"/api/widget/conversations/{world.ticket_a.id}/messages/"
        with _rates(widget_ip="3/min"):
            statuses = [
                APIClient().get("/api/widget/config/", config, HTTP_ORIGIN=ORIGIN).status_code,
                client.get(url).status_code,
                APIClient().get("/api/widget/config/", config, HTTP_ORIGIN=ORIGIN).status_code,
                client.get(url).status_code,
            ]
        self.assertEqual(statuses, [200, 200, 200, 429])

    def test_a_flood_from_a_spoofed_origin_is_throttled_too(self):
        world = make_world()
        with _rates(widget_ip="2/min"):
            responses = [
                APIClient().get(
                    "/api/widget/config/",
                    {"key": world.site.key},
                    HTTP_ORIGIN="https://evil.example",
                )
                for _attempt in range(3)
            ]
        self.assertEqual([response.status_code for response in responses], [403, 403, 429])
        self.assertGreater(int(responses[2]["Retry-After"]), 0)

    def test_uploads_have_their_own_budget(self):
        world = make_world()
        client = visitor_client(world.visitor_a)
        url = f"/api/widget/conversations/{world.ticket_a.id}/attachments/"
        with _rates(widget_upload="2/hour"):
            statuses = [
                client.post(url, {"file": upload(b"hello")}).status_code for _attempt in range(3)
            ]
            message = client.post(
                f"/api/widget/conversations/{world.ticket_a.id}/messages/",
                {"body": "still fine"},
                format="json",
            )
        self.assertEqual(statuses, [201, 201, 429])
        self.assertEqual(message.status_code, 201)

    def test_rejected_uploads_still_spend_the_budget(self):
        world = make_world()
        client = visitor_client(world.visitor_a)
        url = f"/api/widget/conversations/{world.ticket_a.id}/attachments/"
        before = Comment.objects.count()
        with _rates(widget_upload="2/hour"):
            statuses = [
                client.post(
                    url, {"file": upload(b"#!/bin/sh\n", "a.png", "image/png")}
                ).status_code,
                client.post(
                    url, {"file": upload(b"#!/bin/sh\n", "b.png", "image/png")}
                ).status_code,
                client.post(url, {"file": upload(b"hello")}).status_code,
            ]
        self.assertEqual(statuses, [400, 400, 429])
        self.assertEqual(Comment.objects.count(), before)

    def test_socket_tickets_are_limited_per_visitor(self):
        world = make_world()
        client = visitor_client(world.visitor_a)
        with _rates(widget_visitor="2/min"):
            statuses = [client.post("/api/widget/ws/ticket/").status_code for _attempt in range(3)]
        self.assertEqual(statuses, [200, 200, 429])


class SocketTicketThrottleTests(ThrottleTestCase):
    def test_socket_tickets_are_limited_per_user(self):
        first = client_for(UserFactory())
        second = client_for(UserFactory())
        with _rates(ws_ticket="2/min"):
            statuses = [first.post("/api/ws/ticket/").status_code for _attempt in range(3)]
            other = second.post("/api/ws/ticket/")
        self.assertEqual(statuses, [200, 200, 429])
        self.assertEqual(other.status_code, 200)


class SignedDownloadThrottleTests(ThrottleTestCase):
    URL = "/api/downloads/not-a-token/"

    def test_signed_downloads_are_limited_per_address(self):
        with _rates(download="2/min"):
            statuses = [APIClient().get(self.URL).status_code for _attempt in range(3)]
            other = APIClient().get(self.URL, REMOTE_ADDR="10.9.9.9")
        self.assertEqual(statuses, [403, 403, 429])
        self.assertEqual(other.status_code, 403)


class WidgetCapacityTests(ThrottleTestCase):
    def _chat(self, site, age=timedelta()):
        ticket = Ticket.objects.create(
            title="chat",
            description="",
            channel=Ticket.Channel.CHAT,
            site=site,
            visitor=VisitorFactory(site=site),
        )
        Ticket.objects.filter(pk=ticket.pk).update(created_at=timezone.now() - age)
        return ticket

    def _start(self, site):
        return APIClient().post(
            START_URL,
            {"site_key": site.key, "body": "hello"},
            format="json",
            HTTP_ORIGIN=ORIGIN,
        )

    def test_old_unassigned_chats_do_not_block_new_starts(self):
        site = SiteFactory(allowed_origins=[ORIGIN])
        self._chat(site, age=timedelta(hours=2))
        with override_settings(
            WIDGET_SITE_MAX_UNASSIGNED_CHATS=1,
            WIDGET_SITE_UNASSIGNED_WINDOW_MINUTES=60,
        ):
            response = self._start(site)
        self.assertEqual(response.status_code, 201)

    def test_recent_unassigned_chats_still_block_new_starts(self):
        site = SiteFactory(allowed_origins=[ORIGIN])
        self._chat(site)
        with override_settings(
            WIDGET_SITE_MAX_UNASSIGNED_CHATS=1,
            WIDGET_SITE_UNASSIGNED_WINDOW_MINUTES=60,
        ):
            response = self._start(site)
        self.assertEqual(response.status_code, 429)
