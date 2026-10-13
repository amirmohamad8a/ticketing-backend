from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

import jwt

from chat.tokens import (
    ALGORITHM,
    TOKEN_KIND,
    InvalidVisitorToken,
    _signing_key,
    decode_visitor_token,
    issue_visitor_token,
)
from core.tests.factories import SiteFactory, VisitorFactory


class VisitorTokenTests(TestCase):
    def setUp(self):
        self.site = SiteFactory()
        self.visitor = VisitorFactory(site=self.site)

    def test_issue_and_decode(self):
        token = issue_visitor_token(self.visitor)
        visitor_id, site_id = decode_visitor_token(token)
        self.assertEqual(visitor_id, self.visitor.pk)
        self.assertEqual(site_id, self.site.pk)

    def test_tampered_token_is_rejected(self):
        token = issue_visitor_token(self.visitor)
        with self.assertRaises(InvalidVisitorToken):
            decode_visitor_token(token + "x")

    def test_expired_token_is_rejected(self):
        with override_settings(VISITOR_TOKEN_LIFETIME_DAYS=0):
            token = issue_visitor_token(self.visitor)
        with self.assertRaises(InvalidVisitorToken):
            decode_visitor_token(token)

    def test_wrong_kind_is_rejected(self):
        payload = {
            "kind": "wrong",
            "visitor_id": self.visitor.pk,
            "site_id": self.site.pk,
            "iat": timezone.now(),
            "exp": timezone.now() + timedelta(days=1),
        }
        token = jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)
        with self.assertRaises(InvalidVisitorToken):
            decode_visitor_token(token)

    def test_missing_fields_are_rejected(self):
        payload = {
            "kind": TOKEN_KIND,
            "iat": timezone.now(),
            "exp": timezone.now() + timedelta(days=1),
        }
        token = jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)
        with self.assertRaises(InvalidVisitorToken):
            decode_visitor_token(token)

    def test_empty_or_non_string_token_is_rejected(self):
        for bad in ("", None, 123, b"bytes"):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidVisitorToken):
                    decode_visitor_token(bad)
