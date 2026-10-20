import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from prometheus_client import REGISTRY
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.throttles import LoginUsernameThrottle
from core.tests.factories import AdminFactory, UserFactory

REGISTER_URL = "/api/auth/register/"
PASSWORD_CHANGE_URL = "/api/auth/password/change/"
REGISTER_PASSWORD = "S3cure-pass-91"
NEW_PASSWORD = "New-pass-7390"


def _rates(**rates):
    return patch.dict(SimpleRateThrottle.THROTTLE_RATES, rates)


def _global_budget_exceeded():
    return REGISTRY.get_sample_value("ticketing_login_global_budget_exceeded_total") or 0


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class ThrottleTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)


class LoginThrottleTests(ThrottleTestCase):
    def setUp(self):
        super().setUp()
        self.user = UserFactory()
        self.client = APIClient()

    def _login(self, password="wrong-pass-1", **extra):
        payload = {"username": self.user.username, "password": password}
        return self.client.post("/api/token/", payload, **extra)

    def test_brute_force_is_stopped_with_429(self):
        with _rates(login="3/min"):
            statuses = [self._login().status_code for _ in range(5)]
        self.assertEqual(statuses, [401, 401, 401, 429, 429])

    def test_throttled_response_uses_the_error_envelope_and_retry_after(self):
        with _rates(login="1/min"):
            self._login()
            response = self._login()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["error"]["code"], "throttled")
        self.assertIsNone(response.data["error"]["details"])
        self.assertGreater(int(response["Retry-After"]), 0)

    def test_the_correct_password_is_blocked_once_the_budget_is_spent(self):
        with _rates(login="2/min"):
            self._login("pass12345")
            self._login("pass12345")
            response = self._login("pass12345")
        self.assertEqual(response.status_code, 429)

    def test_each_ip_address_has_its_own_budget(self):
        with _rates(login="1/min"):
            self._login(REMOTE_ADDR="10.0.0.1")
            blocked = self._login(REMOTE_ADDR="10.0.0.1")
            other = self._login(REMOTE_ADDR="10.0.0.2")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(other.status_code, 401)

    def test_a_spoofed_forwarded_for_header_does_not_reset_the_budget(self):
        with _rates(login="1/min"):
            self._login(HTTP_X_FORWARDED_FOR="1.1.1.1")
            response = self._login(HTTP_X_FORWARDED_FOR="2.2.2.2")
        self.assertEqual(response.status_code, 429)

    def test_counters_live_in_the_cache(self):
        with _rates(login="5/min"):
            self._login()
        self.assertEqual(len(cache.get("throttle_login_127.0.0.1")), 1)


class RegistrationThrottleTests(ThrottleTestCase):
    def test_a_registration_flood_is_stopped(self):
        client = APIClient()
        with _rates(register="2/min"):
            statuses = [
                client.post(
                    REGISTER_URL,
                    {"username": f"flood{index}", "password": REGISTER_PASSWORD},
                    format="json",
                ).status_code
                for index in range(4)
            ]
        self.assertEqual(statuses, [201, 201, 429, 429])


class PasswordChangeThrottleTests(ThrottleTestCase):
    def _change(self, client):
        return client.post(
            PASSWORD_CHANGE_URL,
            {"old_password": "wrong-pass-1", "new_password": NEW_PASSWORD},
            format="json",
        )

    def test_repeated_attempts_are_stopped(self):
        client = _client_for(UserFactory())
        with _rates(password_change="2/min"):
            statuses = [self._change(client).status_code for _ in range(3)]
        self.assertEqual(statuses, [400, 400, 429])

    def test_the_budget_belongs_to_the_user(self):
        first = _client_for(UserFactory())
        second = _client_for(UserFactory())
        with _rates(password_change="1/min"):
            self._change(first)
            blocked = self._change(first)
            other = self._change(second)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(other.status_code, 400)


class UserManagementThrottleTests(ThrottleTestCase):
    def test_user_routes_have_a_stricter_budget(self):
        client = _client_for(AdminFactory())
        with _rates(user_management="2/min"):
            statuses = [client.get("/api/users/").status_code for _ in range(3)]
        self.assertEqual(statuses, [200, 200, 429])


class DefaultThrottleTests(ThrottleTestCase):
    def test_anonymous_requests_share_a_per_ip_budget(self):
        client = APIClient()
        with _rates(anon="2/min"):
            statuses = [
                client.post("/api/token/refresh/", {"refresh": "garbage"}, format="json")
                for _ in range(3)
            ]
        self.assertEqual([response.status_code for response in statuses], [401, 401, 429])

    def test_authenticated_requests_have_a_per_user_budget(self):
        first = _client_for(UserFactory())
        second = _client_for(UserFactory())
        with _rates(user="2/min"):
            statuses = [first.get("/api/auth/me/").status_code for _ in range(3)]
            other = second.get("/api/auth/me/")
        self.assertEqual(statuses, [200, 200, 429])
        self.assertEqual(other.status_code, 200)

    def test_signed_download_links_have_their_own_budget(self):
        client = APIClient()
        with _rates(download="2/min"):
            statuses = [client.get("/api/downloads/garbage/").status_code for _ in range(3)]
        self.assertEqual(statuses, [403, 403, 429])


class LoginUsernameGlobalThrottleTests(ThrottleTestCase):
    def setUp(self):
        super().setUp()
        self.user = UserFactory()

    def _login(self, password="wrong-pass-1", ip="10.0.0.1"):
        return APIClient().post(
            "/api/token/",
            {"username": self.user.username, "password": password},
            REMOTE_ADDR=ip,
        )

    def test_a_botnet_from_many_addresses_is_counted_but_not_delayed(self):
        before = _global_budget_exceeded()
        with _rates(
            login="100/min",
            login_username="100/hour",
            login_username_global="1/hour",
        ):
            first = self._login(ip="10.0.0.1")
            second = self._login(ip="10.0.0.2")
            third = self._login(ip="10.0.0.3")
        self.assertEqual(
            (first.status_code, second.status_code, third.status_code), (401, 401, 401)
        )
        self.assertEqual(_global_budget_exceeded(), before + 2)

    def test_the_global_bucket_logs_and_counts_without_locking_the_account(self):
        before = _global_budget_exceeded()
        with _rates(
            login="100/min",
            login_username="100/hour",
            login_username_global="1/hour",
        ):
            self._login(ip="10.0.0.1")
            with self.assertLogs("accounts.throttles", level="WARNING"):
                response = self._login(password="pass12345", ip="10.0.0.2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(_global_budget_exceeded(), before + 1)


class LoginUsernameConcurrencyTests(ThrottleTestCase):
    def test_parallel_attempts_never_exceed_the_per_username_limit(self):
        limit = 5
        attempts = 40
        previous_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        self.addCleanup(sys.setswitchinterval, previous_interval)
        barrier = Barrier(attempts)
        request = SimpleNamespace(
            data={"username": "Sara"}, headers={}, META={"REMOTE_ADDR": "10.0.0.1"}
        )

        def attempt():
            barrier.wait()
            return LoginUsernameThrottle().allow_request(request, None)

        with (
            _rates(login_username=f"{limit}/hour", login_username_global="1000/hour"),
            ThreadPoolExecutor(max_workers=attempts) as pool,
        ):
            results = list(pool.map(lambda _: attempt(), range(attempts)))
        self.assertEqual(results.count(True), limit)
        self.assertEqual(results.count(False), attempts - limit)
