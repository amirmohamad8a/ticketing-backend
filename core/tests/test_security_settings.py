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
    "STORAGE_BACKEND": "local",
}


def _load_prod(**overrides):
    with patch.dict(os.environ, {**PROD_ENV, **overrides}), patch.dict(sys.modules):
        sys.modules.pop("config.settings.base", None)
        sys.modules.pop("config.settings.prod", None)
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
        self.assertEqual(cache["LOCATION"], self.prod.REDIS_URL)

    def test_throttling_is_configured_for_every_scope(self):
        rest_framework = self.prod.REST_FRAMEWORK
        self.assertEqual(len(rest_framework["DEFAULT_THROTTLE_CLASSES"]), 2)
        scopes = {
            "anon",
            "user",
            "login",
            "register",
            "password_change",
            "user_management",
            "download",
        }
        self.assertEqual(scopes, set(rest_framework["DEFAULT_THROTTLE_RATES"]))

    def test_the_number_of_trusted_proxies_comes_from_the_environment(self):
        self.assertEqual(_load_prod(NUM_PROXIES="2").REST_FRAMEWORK["NUM_PROXIES"], 2)

    def test_revoking_access_tokens_after_a_password_change_is_enabled(self):
        self.assertTrue(self.prod.SIMPLE_JWT["CHECK_REVOKE_TOKEN"])


class JwtSigningTests(TestCase):
    def test_access_tokens_are_signed_with_the_configured_key(self):
        token = str(RefreshToken.for_user(UserFactory()).access_token)
        claims = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
        self.assertIn("user_id", claims)
