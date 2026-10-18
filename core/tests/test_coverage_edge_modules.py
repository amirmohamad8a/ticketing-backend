import hashlib
import importlib
import os
import sys
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from rest_framework.exceptions import APIException, Throttled

from accounts.tasks import flush_expired_tokens
from chat.availability import agents_available
from chat.contact import save_contact
from chat.tasks import convert_to_offline, purge_stale_visitors, sweep_unanswered_chats
from chat.tokens import InvalidVisitorToken, issue_visitor_token
from chat.visitors import resolve_visitor, resume_visitor_session, start_visitor_session
from chat.widget.limits import _count_start, ensure_site_capacity
from chat.widget.pow import SALT as POW_SALT
from chat.widget.pow import issue_challenge, verify_solution
from core.health import (
    _probe_layer,
    all_passed,
    check_cache,
    check_channel_layer,
    check_database,
    run_checks,
)
from core.tests.factories import SiteFactory, TicketFactory, UserFactory, VisitorFactory
from core.tickets import issue_ticket, redeem_ticket
from realtime.limits import MessageRateLimiter, TypingThrottle
from tickets.models import TicketEvent
from tickets.participants import Participant
from tickets.signals import delete_attachment_file
from tickets.tasks import auto_close_resolved, report_orphan_files


class AccountTaskCoverageTests(SimpleTestCase):
    def test_flush_expired_tokens_calls_the_management_command(self):
        with patch("accounts.tasks.call_command") as call_command:
            flush_expired_tokens()
        call_command.assert_called_once_with("flushexpiredtokens")


class ContactCoverageTests(TestCase):
    def test_saving_contact_details_writes_one_contact_event(self):
        ticket = TicketFactory(from_visitor=True)
        visitor = save_contact(ticket, phone="09123456789", email="sara@example.com")
        self.assertEqual((visitor.phone, visitor.email), ("09123456789", "sara@example.com"))
        event = TicketEvent.objects.get(ticket=ticket, field_changed="contact")
        self.assertEqual((event.old_value, event.new_value), ("", "phone, email"))
        self.assertIsNone(event.actor)

        save_contact(ticket, phone="09123456789", email="sara@example.com")
        self.assertEqual(
            TicketEvent.objects.filter(ticket=ticket, field_changed="contact").count(), 1
        )


class AvailabilityCoverageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_the_cache_can_be_disabled(self):
        with override_settings(AGENTS_AVAILABLE_CACHE_SECONDS=0):
            with patch("chat.availability.presence.accepting_agents", return_value=[]):
                self.assertFalse(agents_available())
            with patch("chat.availability.presence.accepting_agents", return_value=[1]):
                self.assertTrue(agents_available())

    def test_the_result_is_cached_when_a_ttl_is_configured(self):
        with override_settings(AGENTS_AVAILABLE_CACHE_SECONDS=60):
            with patch(
                "chat.availability.presence.accepting_agents", return_value=[1]
            ) as accepting:
                self.assertTrue(agents_available())
                self.assertTrue(agents_available())
        accepting.assert_called_once_with()


class ChatTaskCoverageTests(SimpleTestCase):
    def test_tasks_delegate_to_the_services(self):
        with patch("chat.tasks.convert_unanswered_chat", return_value=True) as convert:
            self.assertTrue(convert_to_offline(7))
        convert.assert_called_once_with(7)

        with patch("chat.tasks.convert_due_chats", return_value=2) as sweep:
            self.assertEqual(sweep_unanswered_chats(), 2)
        sweep.assert_called_once_with()

        with patch(
            "chat.tasks.purge_visitors", return_value={"deleted": 1, "redacted": 2}
        ) as purge:
            self.assertEqual(purge_stale_visitors(), {"deleted": 1, "redacted": 2})
        purge.assert_called_once_with()


class WidgetLimitCoverageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.site = SiteFactory()

    @override_settings(WIDGET_SITE_MAX_UNASSIGNED_CHATS=10, WIDGET_SITE_START_LIMIT_PER_HOUR=10)
    def test_capacity_is_allowed_below_both_limits(self):
        ensure_site_capacity(self.site)

    def test_counting_starts_recovers_when_the_cache_counter_disappears(self):
        with patch("chat.widget.limits.cache.incr", side_effect=ValueError):
            self.assertEqual(_count_start(self.site), 1)

    @override_settings(WIDGET_SITE_MAX_UNASSIGNED_CHATS=10)
    def test_too_many_unassigned_chats_is_throttled(self):
        with patch("chat.widget.limits._unassigned_chats", return_value=10):
            with self.assertRaises(Throttled):
                ensure_site_capacity(self.site)

    @override_settings(WIDGET_SITE_MAX_UNASSIGNED_CHATS=10, WIDGET_SITE_START_LIMIT_PER_HOUR=10)
    def test_too_many_starts_is_throttled(self):
        with patch("chat.widget.limits._unassigned_chats", return_value=0):
            with patch("chat.widget.limits._count_start", return_value=11):
                with self.assertRaises(Throttled):
                    ensure_site_capacity(self.site)


class ProofOfWorkCoverageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.site = SiteFactory()

    def _leading_zero_bits(self, digest):
        return len(digest) * 8 - int.from_bytes(digest, "big").bit_length()

    @override_settings(WIDGET_POW_DIFFICULTY=0)
    def test_proof_of_work_is_disabled_by_default(self):
        self.assertEqual(
            issue_challenge(self.site), {"challenge": None, "difficulty": 0, "expires_in": 0}
        )
        verify_solution(self.site, None, None)

    @override_settings(WIDGET_POW_DIFFICULTY=1, WIDGET_POW_TTL_SECONDS=300)
    def test_a_valid_solution_can_only_be_used_once(self):
        challenge = issue_challenge(self.site)["challenge"]
        nonce = next(
            candidate
            for candidate in range(1000)
            if self._leading_zero_bits(hashlib.sha256(f"{challenge}:{candidate}".encode()).digest())
            >= 1
        )
        verify_solution(self.site, challenge, str(nonce))
        with self.assertRaises(Exception):
            verify_solution(self.site, challenge, str(nonce))

    @override_settings(WIDGET_POW_DIFFICULTY=1, WIDGET_POW_TTL_SECONDS=300)
    def test_missing_wrong_site_and_weak_challenges_are_rejected(self):
        with self.assertRaises(Exception):
            verify_solution(self.site, None, "1")
        with self.assertRaises(Exception):
            verify_solution(self.site, "not-a-token", "1")
        other = SiteFactory()
        challenge = issue_challenge(other)["challenge"]
        with self.assertRaises(Exception):
            verify_solution(self.site, challenge, "1")
        weak = signing.dumps({"site": self.site.pk, "bits": 0}, salt=POW_SALT)
        with self.assertRaises(Exception):
            verify_solution(self.site, weak, "1")


class VisitorSessionCoverageTests(TestCase):
    def test_a_token_for_a_missing_visitor_or_inactive_site_is_rejected(self):
        site = SiteFactory()
        visitor = VisitorFactory(site=site)
        token = issue_visitor_token(visitor)
        visitor.delete()
        with self.assertRaises(InvalidVisitorToken):
            resolve_visitor(token)

        visitor = VisitorFactory(site=site)
        token = issue_visitor_token(visitor)
        site.is_active = False
        site.save(update_fields=["is_active"])
        with self.assertRaises(InvalidVisitorToken):
            resolve_visitor(token)

    def test_starting_and_resuming_a_session_returns_the_same_visitor(self):
        site = SiteFactory()
        session = start_visitor_session(site, name="Sara")
        resumed = resume_visitor_session(session.token)
        self.assertEqual(resumed.visitor, session.visitor)

    def test_resolving_touches_an_old_last_seen_timestamp(self):
        site = SiteFactory()
        visitor = VisitorFactory(site=site, last_seen_at=timezone.now() - timedelta(hours=1))
        token = issue_visitor_token(visitor)
        resolved = resolve_visitor(token)
        self.assertGreater(resolved.last_seen_at, timezone.now() - timedelta(minutes=1))


class RealtimeLimitCoverageTests(SimpleTestCase):
    def test_message_rate_limiter_counts_and_expires(self):
        limiter = MessageRateLimiter(2, 60)
        self.assertTrue(limiter.allow())
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())

    def test_typing_throttle_tracks_state(self):
        throttle = TypingThrottle(10)
        self.assertTrue(throttle.allow(1, True))
        self.assertFalse(throttle.allow(1, True))
        self.assertTrue(throttle.is_typing(1))
        self.assertEqual(throttle.active_tickets(), [1])
        self.assertTrue(throttle.allow(1, False))
        self.assertFalse(throttle.allow(1, False))
        self.assertFalse(throttle.is_typing(1))
        throttle.clear(1)
        self.assertEqual(throttle.active_tickets(), [])


class RealtimeTicketCoverageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_a_ticket_needs_exactly_one_identity(self):
        with self.assertRaises(ValueError):
            issue_ticket(None)
        with self.assertRaises(ValueError):
            Participant()
        with self.assertRaises(ValueError):
            Participant(user=UserFactory(), visitor=VisitorFactory())

    def test_a_ticket_can_only_be_redeemed_once(self):
        user = UserFactory()
        token = issue_ticket(Participant(user=user))["ticket"]
        self.assertEqual(redeem_ticket(token), {"user_id": user.pk})
        self.assertIsNone(redeem_ticket(token))

    def test_bad_tokens_and_failed_deletes_return_none(self):
        for token in ("", "short", "x" * 200, None, 12):
            with self.subTest(token=token):
                self.assertIsNone(redeem_ticket(token))
        token = issue_ticket(Participant(user=UserFactory()))["ticket"]
        with patch("core.tickets.cache.delete", return_value=False):
            self.assertIsNone(redeem_ticket(token))


class AttachmentSignalCoverageTests(TestCase):
    def test_attachments_without_a_file_are_ignored(self):
        delete_attachment_file(sender=None, instance=SimpleNamespace(file=None))
        delete_attachment_file(sender=None, instance=SimpleNamespace(file=SimpleNamespace(name="")))

    def test_a_failed_delete_is_logged(self):
        storage = SimpleNamespace(delete=lambda name: (_ for _ in ()).throw(RuntimeError()))
        instance = SimpleNamespace(file=SimpleNamespace(name="attachments/a.txt", storage=storage))
        with self.assertLogs("tickets.signals", level="WARNING"):
            with self.captureOnCommitCallbacks(execute=True):
                delete_attachment_file(sender=None, instance=instance)


class TicketTaskCoverageTests(SimpleTestCase):
    def test_orphan_report_logs_the_count(self):
        with patch("tickets.tasks.find_orphan_files", return_value=[]):
            self.assertEqual(report_orphan_files(), 0)
        with patch("tickets.tasks.find_orphan_files", return_value=["a.txt"]):
            with self.assertLogs("tickets.tasks", level="WARNING"):
                self.assertEqual(report_orphan_files(), 1)

    def test_auto_close_delegates_to_the_lifecycle_service(self):
        with patch("tickets.tasks.close_due_tickets", return_value=2) as close:
            self.assertEqual(auto_close_resolved(), 2)
        close.assert_called_once_with()


class HealthCoverageTests(TestCase):
    def test_each_check_reports_its_failure(self):
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql):
                return None

            def fetchone(self):
                return None

        with patch("core.health.connection.cursor", return_value=Cursor()):
            with self.assertRaises(RuntimeError):
                check_database()
        with patch("core.health.cache.get", return_value="wrong"):
            with self.assertRaises(RuntimeError):
                check_cache()
        with patch("core.health.get_channel_layer", return_value=None):
            with self.assertRaises(RuntimeError):
                check_channel_layer()

    def test_the_channel_probe_rejects_an_unexpected_message(self):
        class Layer:
            async def new_channel(self):
                return "channel"

            async def send(self, channel, message):
                return None

            async def receive(self, channel):
                return {"type": "unexpected"}

        import asyncio

        with self.assertRaises(RuntimeError):
            asyncio.run(_probe_layer(Layer()))

    def test_run_checks_reports_errors_and_successes(self):
        checks = (
            ("database", lambda: (_ for _ in ()).throw(RuntimeError("db"))),
            ("cache", lambda: None),
            ("channel_layer", lambda: None),
        )
        with patch("core.health.CHECKS", checks):
            with self.assertLogs("core.health", level="WARNING"):
                results = run_checks()
        self.assertEqual(results, {"database": "error", "cache": "ok", "channel_layer": "ok"})
        self.assertFalse(all_passed(results))
        self.assertTrue(all_passed({"database": "ok"}))


class UserThrottleCoverageTests(SimpleTestCase):
    def _request(self, data, remote="1.2.3.4"):
        return SimpleNamespace(data=data, headers={}, META={"REMOTE_ADDR": remote})

    def test_usernames_are_normalized_and_missing_values_are_ignored(self):
        from accounts.throttles import LoginUsernameThrottle

        throttle = LoginUsernameThrottle()
        self.assertEqual(throttle._username(self._request({"username": " Sara "})), "sara")
        for data in ({}, {"username": 1}, {"username": None}):
            with self.subTest(data=data):
                self.assertIsNone(throttle._username(self._request(data)))
        self.assertIsNone(throttle._username(SimpleNamespace(data=None)))

    def test_allow_request_consumes_both_scopes_and_sets_retry_after(self):
        from accounts.throttles import LoginUsernameThrottle

        cache.clear()
        self.addCleanup(cache.clear)
        throttle = LoginUsernameThrottle()
        request = self._request({"username": "Sara"})
        rates = {"login_username": "2/min", "login_username_global": "100/hour"}
        with patch.object(throttle, "THROTTLE_RATES", rates):
            self.assertIsNotNone(throttle.get_cache_key(request, None))
            self.assertTrue(throttle.allow_request(request, None))
            self.assertTrue(throttle.allow_request(request, None))
            self.assertFalse(throttle.allow_request(request, None))
            self.assertIsInstance(throttle.wait(), int)

        with patch.object(throttle, "THROTTLE_RATES", {}):
            self.assertTrue(throttle._consume("missing", "raw"))
        self.assertIsNone(throttle.get_cache_key(self._request({}), None))

    def test_missing_username_parse_rate_and_expired_history_paths(self):
        from accounts.throttles import LoginUsernameThrottle

        cache.clear()
        self.addCleanup(cache.clear)
        throttle = LoginUsernameThrottle()
        self.assertTrue(throttle.allow_request(self._request({}), None))
        with patch.object(throttle, "THROTTLE_RATES", {"raw": "whatever"}):
            with patch.object(throttle, "parse_rate", return_value=(None, None)):
                self.assertTrue(throttle._consume("raw", "raw"))
        key = throttle._key("login_username", "raw")
        cache.set(key, [0], 60)
        with patch.object(throttle, "THROTTLE_RATES", {"login_username": "2/min"}):
            self.assertTrue(throttle._consume("login_username", "raw"))

    def test_an_api_exception_while_reading_the_request_means_no_username(self):
        from accounts.throttles import LoginUsernameThrottle

        class BrokenRequest:
            @property
            def data(self):
                raise APIException("broken")

        self.assertIsNone(LoginUsernameThrottle()._username(BrokenRequest()))

    def test_the_global_limit_slowdown_is_applied(self):
        from accounts.throttles import LoginUsernameThrottle

        throttle = LoginUsernameThrottle()
        request = self._request({"username": "Sara"})
        with patch.object(throttle, "_consume", side_effect=[True, False]):
            with patch("accounts.throttles.time.sleep") as sleep:
                self.assertTrue(throttle.allow_request(request, None))
        sleep.assert_called_once_with(0.5)


class MetricsCoverageTests(SimpleTestCase):
    def test_the_middleware_skips_metrics_and_handles_unmatched_methods(self):
        from core.metrics import RequestMetricsMiddleware

        middleware = RequestMetricsMiddleware(lambda request: SimpleNamespace(status_code=200))
        middleware(SimpleNamespace(path="/metrics/", method="GET"))
        response = middleware(SimpleNamespace(path="/unknown/", method="BREW", resolver_match=None))
        self.assertEqual(response.status_code, 200)

    def test_the_database_collector_swallows_errors(self):
        from stats.metrics import DatabaseCollector

        with patch("stats.metrics.queue_size", side_effect=RuntimeError("db")):
            with self.assertLogs("stats.metrics", level="ERROR"):
                self.assertEqual(list(DatabaseCollector().collect()), [])

    def test_render_metrics_returns_prometheus_text(self):
        from core.metrics import render_metrics

        self.assertIn(b"ticketing", render_metrics())


class ConfigSettingsCoverageTests(SimpleTestCase):
    def _run(self, **overrides):
        environment = {
            "SECRET_KEY": "settings-coverage-secret",
            "DATABASE_URL": "postgres://ticketing:ticketing@localhost:5432/ticketing",
            "STORAGE_BACKEND": "local",
            **overrides,
        }
        with patch.dict(os.environ, environment), patch.dict(sys.modules):
            for name in list(sys.modules):
                if name == "config.settings" or name.startswith("config.settings."):
                    sys.modules.pop(name, None)
            return vars(importlib.import_module("config.settings.base"))

    def test_the_database_url_is_required(self):
        with self.assertRaises(ImproperlyConfigured):
            self._run(DATABASE_URL="")

    def test_the_database_url_must_be_postgres(self):
        with self.assertRaises(ImproperlyConfigured):
            self._run(DATABASE_URL="sqlite:///db.sqlite3")

    def test_the_s3_storage_branch_is_configurable(self):
        namespace = self._run(
            STORAGE_BACKEND="s3",
            S3_BUCKET_NAME="bucket",
            S3_ACCESS_KEY="key",
            S3_SECRET_KEY="secret",
        )
        self.assertEqual(
            namespace["STORAGES"]["default"]["BACKEND"], "core.storage.PresignedS3Storage"
        )

    def test_an_unknown_storage_backend_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            self._run(STORAGE_BACKEND="ftp")
