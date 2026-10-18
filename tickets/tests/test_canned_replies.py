from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.test import TestCase

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.search import ARABIC_YEH, PERSIAN_YEH
from core.tests.factories import AdminFactory, AgentFactory, CannedReplyFactory, UserFactory
from tickets.models import CannedReply

URL = "/api/canned-replies/"
KEYS = {"id", "title", "shortcut", "body", "created_at", "updated_at"}

ROLES = ["unauthenticated", "customer", "agent", "admin"]
EXPECTED = {
    "list": (401, 403, 200, 200),
    "retrieve": (401, 403, 200, 200),
    "create": (401, 403, 201, 201),
    "update": (401, 403, 200, 200),
    "delete": (401, 403, 204, 204),
    "put": (401, 403, 405, 405),
}
MATRIX = [
    (role, action, statuses[index])
    for action, statuses in EXPECTED.items()
    for index, role in enumerate(ROLES)
]


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("role,action,expected_status", MATRIX)
def test_canned_reply_permission_matrix(role, action, expected_status):
    users = {"customer": UserFactory(), "agent": AgentFactory(), "admin": AdminFactory()}
    target = CannedReplyFactory()
    detail_url = f"{URL}{target.id}/"
    client = APIClient()
    if role != "unauthenticated":
        refresh = RefreshToken.for_user(users[role])
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    if action == "list":
        response = client.get(URL)
    elif action == "retrieve":
        response = client.get(detail_url)
    elif action == "create":
        payload = {"title": "Matrix", "shortcut": "matrix-new", "body": "Body"}
        response = client.post(URL, payload, format="json")
    elif action == "update":
        response = client.patch(detail_url, {"title": "Renamed"}, format="json")
    elif action == "delete":
        response = client.delete(detail_url)
    elif action == "put":
        payload = {"title": "Put", "shortcut": "put-reply", "body": "Body"}
        response = client.put(detail_url, payload, format="json")

    assert response.status_code == expected_status


class CannedReplyCreateTests(TestCase):
    def setUp(self):
        self.client = _client_for(AdminFactory())

    def _create(self, **overrides):
        payload = {"title": "Greeting", "shortcut": "greeting", "body": "Hello!"}
        payload.update(overrides)
        return self.client.post(URL, payload, format="json")

    def _assert_rejected(self, response, field):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])
        self.assertFalse(CannedReply.objects.exists())

    def test_a_reply_is_created_and_returned(self):
        response = self._create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), KEYS)
        stored = CannedReply.objects.get()
        self.assertEqual(response.data["id"], stored.id)
        self.assertEqual(
            (stored.title, stored.shortcut, stored.body), ("Greeting", "greeting", "Hello!")
        )

    def test_agents_can_create_replies_too(self):
        response = _client_for(AgentFactory()).post(
            URL, {"title": "t", "shortcut": "agent-made", "body": "b"}, format="json"
        )
        self.assertEqual(response.status_code, 201)

    def test_shortcuts_are_normalized(self):
        cases = [
            ("/Greeting", "greeting"),
            ("  /Hello ", "hello"),
            (f"a{ARABIC_YEH}", f"a{PERSIAN_YEH}"),
            ("code\u06f1", "code1"),
        ]
        for index, (raw, expected) in enumerate(cases):
            with self.subTest(raw=raw):
                response = self._create(shortcut=raw, title=f"Reply {index}")
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data["shortcut"], expected)

    def test_invalid_shortcuts_are_rejected(self):
        for shortcut in ("has space", "bad!", "", "/", "a/b", "x" * 33):
            with self.subTest(shortcut=shortcut):
                self._assert_rejected(self._create(shortcut=shortcut), "shortcut")

    def test_a_shortcut_of_the_maximum_length_is_accepted(self):
        self.assertEqual(self._create(shortcut="x" * 32).status_code, 201)

    def test_shortcuts_must_be_unique_in_every_spelling(self):
        CannedReplyFactory(shortcut="greeting")
        CannedReplyFactory(shortcut="code1")
        for shortcut in ("greeting", "/GREETING", "code\u06f1"):
            with self.subTest(shortcut=shortcut):
                response = self._create(shortcut=shortcut)
                self.assertEqual(response.status_code, 400)
                self.assertIn("shortcut", response.data["error"]["details"])
        self.assertEqual(CannedReply.objects.count(), 2)

    def test_missing_fields_are_reported_together(self):
        response = self.client.post(URL, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.data["error"]["details"]), {"title", "shortcut", "body"})

    def test_title_and_body_have_length_limits(self):
        self._assert_rejected(self._create(title="x" * 101), "title")
        self._assert_rejected(self._create(body="x" * 4001), "body")
        self.assertEqual(self._create(body="x" * 4000).status_code, 201)

    def test_persian_text_is_accepted(self):
        response = self._create(
            title="\u062e\u0648\u0634\u200c\u0622\u0645\u062f",
            shortcut="\u0633\u0644\u0627\u0645",
            body="\u0633\u0644\u0627\u0645!",
        )
        self.assertEqual(response.status_code, 201)

    def test_read_only_fields_are_ignored(self):
        response = self._create(id=999999, created_at="2000-01-01T00:00:00Z")
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.data["id"], 999999)
        self.assertNotEqual(response.data["created_at"][:4], "2000")


class CannedReplyReadUpdateDeleteTests(TestCase):
    def setUp(self):
        self.client = _client_for(AgentFactory())
        self.reply = CannedReplyFactory(shortcut="greeting", title="Greeting", body="Hi")

    def test_list_is_not_paginated_and_sorted_by_shortcut(self):
        CannedReply.objects.all().delete()
        for shortcut in ("c-reply", "a-reply", "b-reply"):
            CannedReplyFactory(shortcut=shortcut)
        response = self.client.get(URL)
        self.assertIsInstance(response.data, list)
        self.assertEqual(
            [row["shortcut"] for row in response.data], ["a-reply", "b-reply", "c-reply"]
        )

    def test_a_long_list_is_returned_in_full(self):
        CannedReplyFactory.create_batch(30)
        self.assertEqual(len(self.client.get(URL).data), 31)

    def test_retrieve_returns_one_reply(self):
        response = self.client.get(f"{URL}{self.reply.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), KEYS)
        self.assertEqual(response.data["shortcut"], "greeting")

    def test_unknown_reply_returns_404(self):
        response = self.client.get(f"{URL}999999/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "not_found")

    def test_patch_changes_only_the_sent_fields(self):
        response = self.client.patch(f"{URL}{self.reply.id}/", {"body": "New body"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.reply.refresh_from_db()
        self.assertEqual(
            (self.reply.title, self.reply.shortcut, self.reply.body),
            ("Greeting", "greeting", "New body"),
        )

    def test_a_reply_can_keep_its_own_shortcut_on_update(self):
        response = self.client.patch(
            f"{URL}{self.reply.id}/", {"shortcut": "/Greeting", "title": "Renamed"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["shortcut"], "greeting")

    def test_a_reply_cannot_take_another_replys_shortcut(self):
        CannedReplyFactory(shortcut="closing")
        response = self.client.patch(
            f"{URL}{self.reply.id}/", {"shortcut": "closing"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("shortcut", response.data["error"]["details"])

    def test_delete_removes_the_reply(self):
        response = self.client.delete(f"{URL}{self.reply.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(CannedReply.objects.filter(pk=self.reply.pk).exists())


class CannedReplyModelTests(TestCase):
    def test_str_shows_the_slash_command(self):
        self.assertEqual(str(CannedReplyFactory(shortcut="hi")), "/hi")

    def test_model_validation_rejects_a_bad_shortcut(self):
        reply = CannedReply(title="t", body="b", shortcut="Hi There")
        with self.assertRaises(ValidationError) as caught:
            reply.full_clean()
        self.assertIn("shortcut", caught.exception.message_dict)

    def test_model_validation_rejects_a_long_body(self):
        reply = CannedReply(title="t", body="x" * 4001, shortcut="ok")
        with self.assertRaises(ValidationError) as caught:
            reply.full_clean()
        self.assertIn("body", caught.exception.message_dict)

    def test_replies_are_ordered_by_shortcut(self):
        second = CannedReplyFactory(shortcut="b")
        first = CannedReplyFactory(shortcut="a")
        self.assertEqual(list(CannedReply.objects.all()), [first, second])

    def test_the_admin_registers_replies_with_search(self):
        admin_instance = site._registry[CannedReply]
        for field in ("shortcut", "title", "body"):
            self.assertIn(field, admin_instance.search_fields)
