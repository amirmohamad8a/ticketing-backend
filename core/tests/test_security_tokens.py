import base64
import json
from datetime import timedelta

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

import jwt
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import User
from chat.models import Visitor
from chat.tokens import TOKEN_KIND, _signing_key, issue_visitor_token
from core.tests.factories import AdminFactory, UserFactory, VisitorFactory
from core.tests.security_support import make_world, visitor_client

WRONG_KEY = "x" * 64


def _decode_part(part):
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def _encode_part(data):
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _flip_signature(token):
    head, body, signature = token.split(".")
    chars = list(signature)
    chars[10] = "A" if chars[10] != "A" else "B"
    return ".".join([head, body, "".join(chars)])


def _with_claims(token, **claims):
    head, body, signature = token.split(".")
    return ".".join([head, _encode_part({**_decode_part(body), **claims}), signature])


def _me_status(authorization):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=authorization)
    return client.get("/api/auth/me/").status_code


def _bearer_status(token):
    return _me_status(f"Bearer {token}")


class AccessTokenTamperingTests(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.admin = AdminFactory()
        self.access = AccessToken.for_user(self.user)
        self.token = str(self.access)
        self.claims = dict(self.access.payload)

    def test_the_untouched_token_is_accepted(self):
        self.assertEqual(_bearer_status(self.token), 200)

    def test_a_modified_signature_is_rejected(self):
        self.assertEqual(_bearer_status(_flip_signature(self.token)), 401)

    def test_a_modified_payload_is_rejected(self):
        forged = _with_claims(self.token, user_id=self.admin.id)
        self.assertEqual(_bearer_status(forged), 401)

    def test_a_token_without_a_signature_is_rejected(self):
        forged = jwt.encode({**self.claims, "user_id": self.admin.id}, "", algorithm="none")
        self.assertEqual(_bearer_status(forged), 401)

    def test_a_token_signed_with_another_key_is_rejected(self):
        forged = jwt.encode(self.claims, WRONG_KEY, algorithm="HS256")
        self.assertEqual(_bearer_status(forged), 401)

    def test_a_token_signed_with_another_algorithm_is_rejected(self):
        forged = jwt.encode(self.claims, settings.JWT_SIGNING_KEY, algorithm="HS512")
        self.assertEqual(_bearer_status(forged), 401)

    def test_a_token_without_a_user_is_rejected(self):
        claims = {key: value for key, value in self.claims.items() if key != "user_id"}
        forged = jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")
        self.assertEqual(_bearer_status(forged), 401)

    def test_an_expired_token_is_rejected(self):
        self.access.set_exp(lifetime=timedelta(seconds=-10))
        self.assertEqual(_bearer_status(str(self.access)), 401)

    def test_a_refresh_token_is_not_an_access_token(self):
        refresh = str(RefreshToken.for_user(self.user))
        self.assertEqual(_bearer_status(refresh), 401)

    def test_an_access_token_is_not_a_refresh_token(self):
        response = APIClient().post("/api/token/refresh/", {"refresh": self.token})
        self.assertEqual(response.status_code, 401)

    def test_a_tampered_refresh_token_is_rejected(self):
        refresh = str(RefreshToken.for_user(self.user))
        response = APIClient().post("/api/token/refresh/", {"refresh": _flip_signature(refresh)})
        self.assertEqual(response.status_code, 401)

    def test_a_token_of_a_deleted_or_deactivated_user_is_rejected(self):
        other = UserFactory()
        deleted = str(AccessToken.for_user(other))
        other.delete()
        self.assertEqual(_bearer_status(deleted), 401)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(_bearer_status(self.token), 401)

    def test_other_authorization_schemes_and_shapes_are_rejected(self):
        headers = [
            f"Token {self.token}",
            f"Basic {self.token}",
            f"bearer {self.token}",
            f"Bearer {self.token} extra",
            "Bearer",
            "Bearer ",
            self.token,
            "",
        ]
        for header in headers:
            with self.subTest(header=header[:20]):
                self.assertEqual(_me_status(header), 401)


class VisitorTokenTamperingTests(TestCase):
    def setUp(self):
        self.world = make_world()
        self.token = issue_visitor_token(self.world.visitor_a)
        self.url = f"/api/widget/conversations/{self.world.ticket_a.id}/messages/"

    def _status(self, token):
        return visitor_client(self.world.visitor_a, token=token).get(self.url).status_code

    def _claims(self, visitor, **overrides):
        now = timezone.now()
        claims = {
            "kind": TOKEN_KIND,
            "visitor_id": visitor.pk,
            "site_id": visitor.site_id,
            "iat": now,
            "exp": now + timedelta(days=1),
        }
        claims.update(overrides)
        return claims

    def test_the_untouched_token_is_accepted(self):
        self.assertEqual(self._status(self.token), 200)

    def test_a_modified_signature_is_rejected(self):
        self.assertEqual(self._status(_flip_signature(self.token)), 401)

    def test_a_token_that_names_another_visitor_is_rejected(self):
        forged = _with_claims(self.token, visitor_id=self.world.visitor_b.pk)
        self.assertEqual(self._status(forged), 401)

    def test_a_token_without_a_signature_is_rejected(self):
        claims = self._claims(self.world.visitor_b)
        forged = jwt.encode(claims, "", algorithm="none")
        self.assertEqual(self._status(forged), 401)

    def test_a_token_signed_with_the_plain_jwt_key_is_rejected(self):
        claims = self._claims(self.world.visitor_a)
        forged = jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")
        self.assertEqual(self._status(forged), 401)

    def test_a_correctly_signed_token_with_the_wrong_site_is_rejected(self):
        from core.tests.factories import SiteFactory

        other_site = SiteFactory()
        claims = self._claims(self.world.visitor_a, site_id=other_site.pk)
        forged = jwt.encode(claims, _signing_key(), algorithm="HS256")
        self.assertEqual(self._status(forged), 401)

    def test_an_expired_token_is_rejected(self):
        with override_settings(VISITOR_TOKEN_LIFETIME_DAYS=0):
            expired = issue_visitor_token(self.world.visitor_a)
        self.assertEqual(self._status(expired), 401)

    def test_a_token_of_a_deleted_visitor_is_rejected(self):
        visitor = VisitorFactory(site=self.world.site)
        token = issue_visitor_token(visitor)
        Visitor.objects.filter(pk=visitor.pk).delete()
        self.assertEqual(self._status(token), 401)

    def test_an_access_token_is_not_a_visitor_token(self):
        access = str(AccessToken.for_user(UserFactory()))
        self.assertEqual(self._status(access), 401)

    def test_a_visitor_token_is_not_an_access_token(self):
        self.assertEqual(_bearer_status(self.token), 401)

    def test_a_missing_or_empty_token_is_rejected(self):
        client = visitor_client(self.world.visitor_a, token=" ")
        self.assertEqual(client.get(self.url).status_code, 401)
        bare = APIClient()
        bare.credentials(HTTP_ORIGIN="https://example.com")
        self.assertEqual(bare.get(self.url).status_code, 401)
