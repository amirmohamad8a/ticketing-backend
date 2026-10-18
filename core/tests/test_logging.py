import json
import logging
import sys
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from celery.signals import setup_logging

from core.logs import REDACTED, JsonFormatter, request_id_var, scrub, user_id_var


def _record(message="hello", args=(), level=logging.INFO, exc_info=None, **extra):
    record = logging.LogRecord("tests.logger", level, __file__, 10, message, args, exc_info)
    record.__dict__.update(extra)
    return record


def _raw(record):
    return JsonFormatter().format(record)


def _format(record):
    return json.loads(_raw(record))


class JsonFormatterTests(SimpleTestCase):
    def _bind(self, request_id=None, user_id=None):
        request_token = request_id_var.set(request_id)
        user_token = user_id_var.set(user_id)
        self.addCleanup(request_id_var.reset, request_token)
        self.addCleanup(user_id_var.reset, user_token)

    def test_a_record_becomes_one_line_of_valid_json(self):
        raw = _raw(_record("hello"))
        self.assertNotIn("\n", raw)
        payload = json.loads(raw)
        self.assertEqual(payload["message"], "hello")
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "tests.logger")

    def test_the_timestamp_is_utc_iso_8601(self):
        timestamp = _format(_record())["timestamp"]
        self.assertTrue(timestamp.endswith("+00:00"))
        self.assertRegex(timestamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$")

    def test_message_arguments_are_rendered(self):
        payload = _format(_record("user %s did %s", ("sara", "login")))
        self.assertEqual(payload["message"], "user sara did login")

    def test_ids_are_null_outside_a_request(self):
        payload = _format(_record())
        self.assertIsNone(payload["request_id"])
        self.assertIsNone(payload["user_id"])

    def test_ids_come_from_the_request_context(self):
        self._bind("abc12345", 42)
        payload = _format(_record())
        self.assertEqual(payload["request_id"], "abc12345")
        self.assertEqual(payload["user_id"], 42)

    def test_persian_text_is_not_escaped(self):
        raw = _raw(_record("سلام دنیا"))
        self.assertIn("سلام دنیا", raw)

    def test_extra_fields_are_included(self):
        payload = _format(_record(order_id=5, status=200))
        self.assertEqual(payload["order_id"], 5)
        self.assertEqual(payload["status"], 200)

    def test_standard_record_attributes_are_not_leaked(self):
        payload = _format(_record())
        for key in ("pathname", "args", "msg", "lineno", "process", "thread", "exc_info"):
            self.assertNotIn(key, payload)

    def test_the_request_object_is_never_serialised(self):
        payload = _format(_record(request=object(), status_code=404))
        self.assertNotIn("request", payload)
        self.assertEqual(payload["status_code"], 404)

    def test_context_ids_cannot_be_overridden_by_extra_fields(self):
        self._bind("abc12345", 42)
        payload = _format(_record(request_id="forged", user_id=1))
        self.assertEqual(payload["request_id"], "abc12345")
        self.assertEqual(payload["user_id"], 42)

    def test_values_that_are_not_json_serialisable_become_strings(self):
        payload = _format(_record(thing=object))
        self.assertIsInstance(payload["thing"], str)

    def test_sensitive_extra_fields_are_masked(self):
        payload = _format(
            _record(
                password="hunter2",
                refresh="abc",
                access="def",
                Authorization="Bearer x",
                api_key="k",
                signature="s",
                note="fine",
            )
        )
        for key in ("password", "refresh", "access", "Authorization", "api_key", "signature"):
            with self.subTest(key=key):
                self.assertEqual(payload[key], REDACTED)
        self.assertEqual(payload["note"], "fine")

    def test_sensitive_keys_are_masked_inside_nested_values(self):
        payload = _format(
            _record(headers={"Cookie": "a=b", "Accept": "json"}, rows=[{"token": "t"}])
        )
        self.assertEqual(payload["headers"], {"Cookie": REDACTED, "Accept": "json"})
        self.assertEqual(payload["rows"], [{"token": REDACTED}])

    def test_extra_strings_are_scrubbed(self):
        payload = _format(_record(url="/api/downloads/abc:def/"))
        self.assertEqual(payload["url"], "/api/downloads/[redacted]/")

    def test_message_text_is_scrubbed_after_formatting(self):
        payload = _format(_record("Forbidden: %s", ("/api/downloads/abc:def-ghi/",)))
        self.assertEqual(payload["message"], "Forbidden: /api/downloads/[redacted]/")

    def test_exceptions_are_logged_on_a_single_line_and_scrubbed(self):
        try:
            raise ValueError("failed /api/downloads/SECRET:TOKEN/")
        except ValueError:
            exc_info = sys.exc_info()
        raw = _raw(_record("oops", level=logging.ERROR, exc_info=exc_info))
        self.assertNotIn("\n", raw)
        exception = json.loads(raw)["exception"]
        self.assertIn("Traceback", exception)
        self.assertIn("ValueError", exception)
        self.assertNotIn("SECRET:TOKEN", exception)
        self.assertIn("/api/downloads/[redacted]/", exception)


class ScrubTests(SimpleTestCase):
    def test_secrets_are_replaced(self):
        cases = [
            ("GET /api/downloads/abc:def-ghi/ 403", "GET /api/downloads/[redacted]/ 403"),
            ("Authorization: Bearer abc.def-ghi_jkl", "Authorization: Bearer [redacted]"),
            (
                "token eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoxfQ.c2lnbmF0dXJl end",
                "token [redacted] end",
            ),
            ("/x/?a=1&refresh=abc123&b=2", "/x/?a=1&refresh=[redacted]&b=2"),
            (
                "https://h/b/k?X-Amz-Signature=abcdef&X-Amz-Expires=60",
                "https://h/b/k?X-Amz-Signature=[redacted]&X-Amz-Expires=60",
            ),
            ("/x/?password=hunter2", "/x/?password=[redacted]"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(scrub(text), expected)

    def test_ordinary_text_is_left_alone(self):
        for text in ("GET /api/tickets/5/ 200", "/x/?page=2&status=open", "سلام دنیا"):
            with self.subTest(text=text):
                self.assertEqual(scrub(text), text)

    def test_scrubbing_twice_changes_nothing(self):
        once = scrub("Bearer abc.def /api/downloads/xyz/ ?token=1")
        self.assertEqual(scrub(once), once)


class LoggingSettingsTests(SimpleTestCase):
    def test_the_root_logger_writes_json_to_the_console(self):
        config = settings.LOGGING
        self.assertEqual(config["root"]["handlers"], ["console"])
        self.assertEqual(config["handlers"]["console"]["formatter"], "json")
        self.assertEqual(config["formatters"]["json"]["()"], "core.logs.JsonFormatter")

    def test_the_level_comes_from_log_level(self):
        self.assertEqual(settings.LOGGING["root"]["level"], settings.LOG_LEVEL)
        self.assertEqual(settings.LOGGING["loggers"]["django"]["level"], settings.LOG_LEVEL)

    def test_client_errors_are_left_to_the_access_log(self):
        self.assertEqual(settings.LOGGING["loggers"]["django.request"]["level"], "ERROR")

    def test_the_runserver_request_log_is_silenced(self):
        config = settings.LOGGING["loggers"]["django.server"]
        self.assertEqual(config["handlers"], ["null"])
        self.assertFalse(config["propagate"])

    def test_logging_is_applied_to_the_root_logger(self):
        formatters = [handler.formatter for handler in logging.getLogger().handlers]
        self.assertTrue(any(isinstance(formatter, JsonFormatter) for formatter in formatters))

    def test_the_request_id_header_is_exposed_to_browsers(self):
        self.assertIn("X-Request-ID", settings.CORS_EXPOSE_HEADERS)

    def test_the_request_id_middleware_runs_first(self):
        self.assertEqual(settings.MIDDLEWARE[0], "core.middleware.RequestIdMiddleware")


class CeleryLoggingTests(SimpleTestCase):
    def test_the_worker_uses_the_project_logging_configuration(self):
        with patch("logging.config.dictConfig") as configure:
            setup_logging.send(sender=None)
        configure.assert_called_once_with(settings.LOGGING)
