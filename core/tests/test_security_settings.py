import importlib
import os
import sys
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase

import jwt
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import UserFactory

PROD_ENV = {
    "SECRET_KEY": "x1y2z3" * 12,
    "JWT_SIGNING_KEY": "a9b8c7" * 12,
    "ALLOWED_HOSTS": "support.example.com",
    "DATABASE_URL": "postgres://ticketing:ticketing@localhost:5432/ticketing",
    "STORAGE_BACKEND": "local",
    "SECURE_SSL_REDIRECT": "true",
    "SECURE_HSTS_SECONDS": "31536000",
    "NUM_PROXIES": "1",
}

PROD_LOGGER = "config.settings.prod"


def _clear_settings_modules():
    for name in list(sys.modules):
        if name == "config.settings" or name.startswith("config.settings."):
            sys.modules.pop(name, None)


def _load_prod(**overrides):
    with patch.dict(os.environ, {**PROD_ENV, **overrides}), patch.dict(sys.modules):
        _clear_settings_modules()
        return importlib.import_module("config.settings.prod")


def _load_prod_without(*names):
    environment = {key: value for key, value in PROD_ENV.items() if key not in names}
    with patch.dict(os.environ, environment, clear=True), patch.dict(sys.modules):
        _clear_settings_modules()
        return importlib.import_module("config.settings.prod")


class ProductionSettingsTests(SimpleTestCase):
    def setUp(self):
        self.prod = _load_prod()

    def test_https_hardening_is_switched_on(self):
        self.assertTrue(self.prod.SECURE_SSL_REDIRECT)
        self.assertGreater(self.prod.SECURE_HSTS_SECONDS, 0)
        self.assertTrue(self.prod.SECURE_HSTS_INCLUDE_SUBDOMAINS)
        self.assertTrue(self.prod.SECURE_HSTS_PRELOAD)
        self.assertTrue(self.prod.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertTrue(self.prod.SESSION_COOKIE_SECURE)
        self.assertTrue(self.prod.CSRF_COOKIE_SECURE)
        self.assertEqual(self.prod.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))

    def test_the_health_check_is_exempt_from_the_https_redirect(self):
        self.assertIn(r"^health/$", self.prod.SECURE_REDIRECT_EXEMPT)

    def test_the_https_redirect_can_be_turned_off_for_plain_http_runs(self):
        self.assertFalse(_load_prod(SECURE_SSL_REDIRECT="false").SECURE_SSL_REDIRECT)

    def test_jwt_tokens_use_their_own_signing_key(self):
        self.assertEqual(self.prod.JWT_SIGNING_KEY, PROD_ENV["JWT_SIGNING_KEY"])
        self.assertEqual(self.prod.SIMPLE_JWT["SIGNING_KEY"], PROD_ENV["JWT_SIGNING_KEY"])
        self.assertNotEqual(self.prod.SIMPLE_JWT["SIGNING_KEY"], self.prod.SECRET_KEY)

    def test_the_signing_key_cannot_be_the_secret_key(self):
        with self.assertRaises(ImproperlyConfigured):
            _load_prod(JWT_SIGNING_KEY=PROD_ENV["SECRET_KEY"])

    def test_the_cache_is_redis_so_throttle_counters_are_shared(self):
        cache = self.prod.CACHES["default"]
        self.assertEqual(cache["BACKEND"], "django.core.cache.backends.redis.RedisCache")
        self.assertEqual(cache["LOCATION"], self.prod.CACHE_REDIS_URL)

    def test_throttling_is_configured_for_every_scope(self):
        rest_framework = self.prod.REST_FRAMEWORK
        self.assertEqual(len(rest_framework["DEFAULT_THROTTLE_CLASSES"]), 2)
        scopes = {
            "anon",
            "user",
            "login",
            "login_username",
            "login_username_global",
            "register",
            "password_change",
            "user_management",
            "site_management",
            "download",
            "export",
            "attachment_upload",
            "ws_ticket",
            "widget_ip",
            "widget_visitor",
            "widget_start",
            "widget_upload",
        }
        self.assertEqual(scopes, set(rest_framework["DEFAULT_THROTTLE_RATES"]))

    def test_the_number_of_trusted_proxies_comes_from_the_environment(self):
        self.assertEqual(_load_prod(NUM_PROXIES="2").REST_FRAMEWORK["NUM_PROXIES"], 2)

    def test_production_refuses_to_start_without_a_proxy_count(self):
        with self.assertRaises(ImproperlyConfigured):
            _load_prod_without("NUM_PROXIES")

    def test_zero_proxies_needs_an_explicit_opt_in(self):
        with self.assertRaises(ImproperlyConfigured):
            _load_prod(NUM_PROXIES="0")
        with self.assertLogs(PROD_LOGGER, level="WARNING") as logs:
            self.assertEqual(_load_prod(NUM_PROXIES="0", ALLOW_ZERO_PROXIES="true").NUM_PROXIES, 0)
        self.assertIn("NUM_PROXIES", logs.output[0])

    def test_no_warning_is_logged_when_a_proxy_is_trusted(self):
        with self.assertNoLogs(PROD_LOGGER, level="WARNING"):
            _load_prod(NUM_PROXIES="1")

    def test_the_request_body_limits_come_from_the_environment(self):
        self.assertEqual(self.prod.MAX_REQUEST_BODY_BYTES, 64 * 1024)
        self.assertEqual(self.prod.MAX_UPLOAD_BODY_BYTES, 11 * 1024 * 1024)
        self.assertEqual(_load_prod(MAX_REQUEST_BODY_BYTES="1024").MAX_REQUEST_BODY_BYTES, 1024)
        self.assertEqual(_load_prod(MAX_UPLOAD_BODY_BYTES="2048").MAX_UPLOAD_BODY_BYTES, 2048)

    def test_proof_of_work_is_on_by_default_in_production(self):
        self.assertEqual(self.prod.WIDGET_POW_DIFFICULTY, 18)
        self.assertEqual(_load_prod(WIDGET_POW_DIFFICULTY="0").WIDGET_POW_DIFFICULTY, 0)

    def test_the_demo_app_is_not_installed_in_production(self):
        self.assertNotIn("demo", self.prod.INSTALLED_APPS)

    def test_api_docs_are_off_in_production_by_default(self):
        self.assertFalse(self.prod.API_DOCS_ENABLED)
        self.assertTrue(_load_prod(API_DOCS_ENABLED="true").API_DOCS_ENABLED)

    def test_api_docs_are_admin_only_when_they_are_enabled_in_production(self):
        self.assertEqual(
            self.prod.SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"],
            ["accounts.permissions.IsAdmin"],
        )

    def test_revoking_access_tokens_after_a_password_change_is_enabled(self):
        self.assertTrue(self.prod.SIMPLE_JWT["CHECK_REVOKE_TOKEN"])


class JwtSigningTests(TestCase):
    def test_access_tokens_are_signed_with_the_configured_key(self):
        token = str(RefreshToken.for_user(UserFactory()).access_token)
        claims = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
        self.assertIn("user_id", claims)
