import os
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings

import redis
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from chat import presence
from core.health import check_cache, run_checks
from core.tests.factories import AgentFactory, UserFactory
from core.tickets import issue_ticket, redeem_ticket
from tickets.participants import Participant

KEY_PREFIX = "ticketing-test"
REQUIRED = os.environ.get("REQUIRE_REDIS") == "1"


def _test_url():
    parts = urlsplit(settings.CACHE_REDIS_URL)
    return urlunsplit(parts._replace(path="/15"))


TEST_URL = _test_url()
REDIS_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": TEST_URL,
        "KEY_PREFIX": KEY_PREFIX,
    }
}


def _reachable():
    try:
        return bool(redis.Redis.from_url(TEST_URL, socket_connect_timeout=1).ping())
    except redis.RedisError:
        return False


REACHABLE = _reachable()


def _raw_key(key):
    return f"{KEY_PREFIX}:1:{key}"


@unittest.skipUnless(REACHABLE or REQUIRED, "Redis is not reachable.")
@override_settings(CACHES=REDIS_CACHES)
class RedisBackedCacheTests(TestCase):
    def setUp(self):
        self.raw = redis.Redis.from_url(TEST_URL)
        cache.clear()
        self.addCleanup(cache.clear)

    def test_values_are_stored_in_redis_with_a_lifetime(self):
        cache.set("probe", {"answer": 42}, timeout=30)
        self.assertEqual(cache.get("probe"), {"answer": 42})
        self.assertEqual(self.raw.exists(_raw_key("probe")), 1)
        self.assertTrue(0 < self.raw.ttl(_raw_key("probe")) <= 30)

    def test_throttle_counters_live_in_redis_and_are_shared_between_clients(self):
        user = UserFactory()
        payload = {"username": user.username, "password": "wrong-pass-1"}
        first, second = APIClient(), APIClient()
        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login": "2/min"}):
            statuses = [
                first.post("/api/token/", payload).status_code,
                second.post("/api/token/", payload).status_code,
                first.post("/api/token/", payload).status_code,
                second.post("/api/token/", payload).status_code,
            ]
        self.assertEqual(statuses, [401, 401, 429, 429])
        self.assertEqual(self.raw.exists(_raw_key("throttle_login_127.0.0.1")), 1)

    def test_presence_is_kept_in_redis(self):
        agent = AgentFactory()
        self.assertEqual(presence.heartbeat(agent.pk), presence.STATUS_AVAILABLE)
        self.assertEqual(presence.available_agent_ids(), [agent.pk])
        self.assertTrue(self.raw.ttl(_raw_key(f"presence:{agent.pk}")) > 0)
        presence.set_status(agent.pk, presence.STATUS_AWAY)
        self.assertEqual(presence.get_statuses([agent.pk]), {agent.pk: presence.STATUS_AWAY})
        self.assertEqual(presence.available_agent_ids(), [])

    def test_websocket_tickets_work_exactly_once(self):
        user = UserFactory()
        token = issue_ticket(Participant(user=user))["ticket"]
        self.assertEqual(redeem_ticket(token), {"user_id": user.pk})
        self.assertIsNone(redeem_ticket(token))

    def test_the_readiness_probe_passes_against_real_redis(self):
        check_cache()
        self.assertEqual(run_checks()["cache"], "ok")
