from django.test import TestCase

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat.models import Site
from chat.pagination import SiteCursorPagination
from core.tests.factories import AdminFactory, AgentFactory, SiteFactory, UserFactory

URL = "/api/sites/"
PAGE_SIZE = SiteCursorPagination.page_size
SITE_KEYS = {
    "id",
    "name",
    "key",
    "allowed_origins",
    "is_active",
    "greeting",
    "primary_color",
    "position",
    "offline_timeout_minutes",
    "require_name",
    "require_contact",
    "created_at",
    "updated_at",
}

ROLES = ["unauthenticated", "customer", "agent", "admin"]
EXPECTED = {
    "list": (401, 403, 403, 200),
    "retrieve": (401, 403, 403, 200),
    "create": (401, 403, 403, 201),
    "update": (401, 403, 403, 200),
    "rotate_key": (401, 403, 403, 200),
    "put": (401, 403, 403, 405),
    "delete": (401, 403, 403, 405),
}
MATRIX = [
    (role, action, statuses[index])
    for action, statuses in EXPECTED.items()
    for index, role in enumerate(ROLES)
]

INVALID_ORIGINS = [
    "",
    "example.com",
    "ftp://example.com",
    "https://example.com/",
    "https://example.com/path",
    "https://example.com?x=1",
    "https://*.example.com",
    "https://example.com:99999",
    "javascript:alert(1)",
    "https://" + "a" * 250 + ".com",
]


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("role,action,expected_status", MATRIX)
def test_site_management_permission_matrix(role, action, expected_status):
    users = {
        "customer": UserFactory(),
        "agent": AgentFactory(),
        "admin": AdminFactory(),
    }
    target = SiteFactory()
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
        response = client.post(URL, {"name": "Matrix site"}, format="json")
    elif action == "update":
        response = client.patch(detail_url, {"name": "Renamed"}, format="json")
    elif action == "rotate_key":
        response = client.post(f"{detail_url}rotate-key/")
    elif action == "put":
        response = client.put(detail_url, {"name": "Replaced"}, format="json")
    elif action == "delete":
        response = client.delete(detail_url)

    assert response.status_code == expected_status


class SiteCreateTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)

    def _create(self, **overrides):
        payload = {"name": "Main site"}
        payload.update(overrides)
        return self.client.post(URL, payload, format="json")

    def _assert_rejected(self, response, field):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])
        self.assertFalse(Site.objects.exists())

    def test_a_name_alone_creates_a_site_with_defaults(self):
        response = self._create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), SITE_KEYS)
        stored = Site.objects.get()
        self.assertEqual(response.data["id"], stored.id)
        self.assertEqual(response.data["key"], stored.key)
        self.assertEqual(response.data["name"], "Main site")
        self.assertEqual(response.data["allowed_origins"], [])
        self.assertTrue(response.data["is_active"])
        self.assertEqual(response.data["greeting"], "")
        self.assertEqual(response.data["primary_color"], "#2563eb")
        self.assertEqual(response.data["position"], "bottom_right")
        self.assertEqual(response.data["offline_timeout_minutes"], 5)
        self.assertFalse(response.data["require_name"])
        self.assertFalse(response.data["require_contact"])

    def test_every_setting_can_be_chosen(self):
        payload = {
            "name": "Docs site",
            "allowed_origins": ["https://docs.example.com", "http://localhost:3000"],
            "is_active": False,
            "greeting": "Hello!",
            "primary_color": "#ff8800",
            "position": "bottom_left",
            "offline_timeout_minutes": 15,
            "require_name": True,
            "require_contact": True,
        }
        response = self._create(**payload)
        self.assertEqual(response.status_code, 201)
        for field, value in payload.items():
            with self.subTest(field=field):
                self.assertEqual(response.data[field], value)
        stored = Site.objects.get()
        self.assertEqual(stored.allowed_origins, payload["allowed_origins"])
        self.assertEqual(stored.position, Site.Position.BOTTOM_LEFT)
        self.assertEqual(stored.offline_timeout_minutes, 15)

    def test_a_created_site_can_be_looked_up_by_its_key(self):
        created = self._create(name="Lookup")
        SiteFactory.create_batch(2)
        found = self.client.get(f"{URL}?key={created.data['key']}")
        self.assertEqual(found.status_code, 200)
        self.assertEqual([item["id"] for item in found.data["results"]], [created.data["id"]])
        self.assertEqual(found.data["results"][0]["name"], "Lookup")

    def test_the_key_is_generated_and_cannot_be_chosen(self):
        response = self._create(key="forged-key")
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.data["key"], "forged-key")
        self.assertRegex(response.data["key"], r"^[A-Za-z0-9_-]{32}$")
        self.assertEqual(Site.objects.get().key, response.data["key"])

    def test_every_site_gets_its_own_key(self):
        keys = {self._create(name=f"Site {index}").data["key"] for index in range(3)}
        self.assertEqual(len(keys), 3)

    def test_read_only_fields_in_the_payload_are_ignored(self):
        response = self._create(id=999999, created_at="2000-01-01T00:00:00Z")
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.data["id"], 999999)
        self.assertNotEqual(response.data["created_at"][:4], "2000")

    def test_origins_are_normalized_and_deduplicated(self):
        response = self._create(
            allowed_origins=[
                "HTTPS://Shop.Example.com:443",
                "https://shop.example.com",
                "http://localhost:3000",
                "  http://localhost:3000  ",
            ]
        )
        self.assertEqual(response.status_code, 201)
        expected = ["https://shop.example.com", "http://localhost:3000"]
        self.assertEqual(response.data["allowed_origins"], expected)
        self.assertEqual(Site.objects.get().allowed_origins, expected)

    def test_invalid_origins_are_rejected(self):
        for origin in INVALID_ORIGINS:
            with self.subTest(origin=origin[:40]):
                self._assert_rejected(self._create(allowed_origins=[origin]), "allowed_origins")

    def test_one_invalid_origin_rejects_the_whole_list(self):
        response = self._create(allowed_origins=["https://ok.example.com", "nope"])
        self._assert_rejected(response, "allowed_origins")

    def test_origins_must_be_a_list(self):
        for value in ("https://example.com", {"origin": "https://example.com"}, 5, None):
            with self.subTest(value=value):
                self._assert_rejected(self._create(allowed_origins=value), "allowed_origins")

    def test_at_most_twenty_origins_are_allowed(self):
        origins = [f"https://site{index}.example.com" for index in range(21)]
        self._assert_rejected(self._create(allowed_origins=origins), "allowed_origins")
        response = self._create(allowed_origins=origins[:20])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["allowed_origins"]), 20)

    def test_invalid_values_are_rejected(self):
        cases = [
            ({"name": ""}, "name"),
            ({"name": "x" * 101}, "name"),
            ({"primary_color": "red"}, "primary_color"),
            ({"primary_color": "#fff"}, "primary_color"),
            ({"position": "top"}, "position"),
            ({"offline_timeout_minutes": 0}, "offline_timeout_minutes"),
            ({"offline_timeout_minutes": -1}, "offline_timeout_minutes"),
            ({"offline_timeout_minutes": 1441}, "offline_timeout_minutes"),
            ({"greeting": "x" * 501}, "greeting"),
            ({"is_active": "maybe"}, "is_active"),
        ]
        for overrides, field in cases:
            with self.subTest(overrides=str(overrides)[:40]):
                self._assert_rejected(self._create(**overrides), field)

    def test_the_name_is_required(self):
        response = self.client.post(URL, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.data["error"]["details"]), {"name"})
        self.assertFalse(Site.objects.exists())

    def test_timeout_boundaries_are_accepted(self):
        for index, minutes in enumerate((1, 1440)):
            with self.subTest(minutes=minutes):
                response = self._create(name=f"Boundary {index}", offline_timeout_minutes=minutes)
                self.assertEqual(response.status_code, 201)

    def test_persian_text_is_accepted(self):
        response = self._create(name="فروشگاه من", greeting="سلام! چطور می‌توانیم کمک کنیم؟")
        self.assertEqual(response.status_code, 201)
        stored = Site.objects.get()
        self.assertEqual(stored.name, "فروشگاه من")
        self.assertEqual(stored.greeting, "سلام! چطور می‌توانیم کمک کنیم؟")


class SiteListTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)

    def _ids(self, response):
        return [item["id"] for item in response.data["results"]]

    def test_list_returns_every_site_in_id_order_with_all_fields(self):
        sites = SiteFactory.create_batch(3)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), sorted(item.id for item in sites))
        self.assertEqual(set(response.data["results"][0]), SITE_KEYS)

    def test_empty_list_has_no_results_and_no_links(self):
        response = self.client.get(URL)
        self.assertEqual(response.data["results"], [])
        self.assertIsNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

    def test_inactive_sites_are_listed(self):
        inactive = SiteFactory(is_active=False)
        self.assertIn(inactive.id, self._ids(self.client.get(URL)))

    def test_key_filter_returns_only_the_matching_site(self):
        target = SiteFactory()
        SiteFactory.create_batch(2)
        response = self.client.get(f"{URL}?key={target.key}")
        self.assertEqual(self._ids(response), [target.id])

    def test_unknown_key_returns_an_empty_page(self):
        SiteFactory()
        response = self.client.get(f"{URL}?key=does-not-exist")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_key_filter_is_an_exact_match(self):
        target = SiteFactory()
        response = self.client.get(f"{URL}?key={target.key[:10]}")
        self.assertEqual(response.data["results"], [])

    def test_is_active_filter(self):
        active = SiteFactory()
        inactive = SiteFactory(is_active=False)
        only_inactive = self.client.get(f"{URL}?is_active=false")
        self.assertEqual(self._ids(only_inactive), [inactive.id])
        only_active = self.client.get(f"{URL}?is_active=true")
        self.assertEqual(self._ids(only_active), [active.id])

    def test_filters_combine(self):
        target = SiteFactory(is_active=False)
        response = self.client.get(f"{URL}?key={target.key}&is_active=true")
        self.assertEqual(response.data["results"], [])
        response = self.client.get(f"{URL}?key={target.key}&is_active=false")
        self.assertEqual(self._ids(response), [target.id])

    def test_list_is_paginated_with_a_cursor(self):
        SiteFactory.create_batch(PAGE_SIZE + 5)
        first = self.client.get(URL)
        self.assertEqual(len(first.data["results"]), PAGE_SIZE)
        self.assertIsNotNone(first.data["next"])
        second = self.client.get(first.data["next"])
        self.assertEqual(len(second.data["results"]), 5)
        self.assertIsNone(second.data["next"])
        walked = self._ids(first) + self._ids(second)
        self.assertEqual(len(set(walked)), PAGE_SIZE + 5)


class SiteRetrieveTests(TestCase):
    def setUp(self):
        self.client = _client_for(AdminFactory())

    def test_admin_can_read_any_site(self):
        for created in (SiteFactory(), SiteFactory(is_active=False)):
            with self.subTest(active=created.is_active):
                response = self.client.get(f"{URL}{created.id}/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(response.data), SITE_KEYS)
                self.assertEqual(response.data["id"], created.id)
                self.assertEqual(response.data["key"], created.key)
                self.assertEqual(response.data["allowed_origins"], created.allowed_origins)

    def test_unknown_site_returns_404(self):
        response = self.client.get(f"{URL}999999/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "not_found")


class SiteUpdateTests(TestCase):
    def setUp(self):
        self.client = _client_for(AdminFactory())
        self.site = SiteFactory(
            name="Original",
            greeting="Hi",
            primary_color="#112233",
            offline_timeout_minutes=7,
            require_name=True,
        )
        self.url = f"{URL}{self.site.id}/"

    def _patch(self, payload):
        return self.client.patch(self.url, payload, format="json")

    def _stored(self):
        return Site.objects.get(pk=self.site.pk)

    def _assert_rejected(self, response, field):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])

    def test_settings_can_be_updated(self):
        payload = {
            "name": "Renamed",
            "allowed_origins": ["https://new.example.com"],
            "is_active": False,
            "greeting": "Welcome",
            "primary_color": "#abcdef",
            "position": "bottom_left",
            "offline_timeout_minutes": 30,
            "require_name": False,
            "require_contact": True,
        }
        response = self._patch(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), SITE_KEYS)
        stored = self._stored()
        for field, value in payload.items():
            with self.subTest(field=field):
                self.assertEqual(response.data[field], value)
                self.assertEqual(getattr(stored, field), value)

    def test_partial_update_changes_only_the_sent_fields(self):
        response = self._patch({"greeting": "Updated"})
        self.assertEqual(response.status_code, 200)
        stored = self._stored()
        self.assertEqual(stored.greeting, "Updated")
        self.assertEqual(stored.name, "Original")
        self.assertEqual(stored.allowed_origins, ["https://example.com"])
        self.assertEqual(stored.primary_color, "#112233")
        self.assertEqual(stored.offline_timeout_minutes, 7)
        self.assertTrue(stored.require_name)
        self.assertEqual(stored.key, self.site.key)

    def test_empty_patch_changes_nothing(self):
        response = self._patch({})
        self.assertEqual(response.status_code, 200)
        stored = self._stored()
        self.assertEqual(stored.name, "Original")
        self.assertEqual(stored.key, self.site.key)

    def test_updating_moves_updated_at_forward(self):
        before = self.site.updated_at
        self._patch({"name": "Renamed"})
        self.assertGreater(self._stored().updated_at, before)

    def test_origins_are_normalized_on_update(self):
        response = self._patch({"allowed_origins": ["HTTP://Localhost:80", "http://localhost"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._stored().allowed_origins, ["http://localhost"])

    def test_origins_can_be_cleared(self):
        response = self._patch({"allowed_origins": []})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._stored().allowed_origins, [])

    def test_invalid_origins_are_rejected_and_nothing_changes(self):
        for origin in INVALID_ORIGINS:
            with self.subTest(origin=origin[:40]):
                response = self._patch({"name": "Changed", "allowed_origins": [origin]})
                self._assert_rejected(response, "allowed_origins")
                stored = self._stored()
                self.assertEqual(stored.name, "Original")
                self.assertEqual(stored.allowed_origins, ["https://example.com"])

    def test_invalid_values_are_rejected_and_nothing_changes(self):
        cases = [
            ({"name": ""}, "name"),
            ({"primary_color": "blue"}, "primary_color"),
            ({"position": "center"}, "position"),
            ({"offline_timeout_minutes": 0}, "offline_timeout_minutes"),
            ({"offline_timeout_minutes": 1441}, "offline_timeout_minutes"),
            ({"greeting": "x" * 501}, "greeting"),
        ]
        for payload, field in cases:
            with self.subTest(payload=str(payload)[:40]):
                self._assert_rejected(self._patch(payload), field)
                stored = self._stored()
                self.assertEqual(stored.name, "Original")
                self.assertEqual(stored.primary_color, "#112233")
                self.assertEqual(stored.offline_timeout_minutes, 7)

    def test_key_id_and_timestamps_cannot_be_changed(self):
        before = self._stored()
        response = self._patch(
            {"key": "forged", "id": 999999, "created_at": "2000-01-01T00:00:00Z"}
        )
        self.assertEqual(response.status_code, 200)
        stored = self._stored()
        self.assertEqual(stored.key, before.key)
        self.assertEqual(stored.id, before.id)
        self.assertEqual(stored.created_at, before.created_at)

    def test_a_site_can_be_deactivated_and_reactivated(self):
        self.assertEqual(self._patch({"is_active": False}).status_code, 200)
        self.assertFalse(self._stored().is_active)
        self.assertEqual(self._patch({"is_active": True}).status_code, 200)
        self.assertTrue(self._stored().is_active)

    def test_unknown_site_returns_404(self):
        response = self.client.patch(f"{URL}999999/", {"name": "x"}, format="json")
        self.assertEqual(response.status_code, 404)


class SiteRotateKeyTests(TestCase):
    def setUp(self):
        self.client = _client_for(AdminFactory())
        self.site = SiteFactory(greeting="Hello", allowed_origins=["https://shop.example.com"])
        self.url = f"{URL}{self.site.id}/rotate-key/"

    def test_rotating_issues_a_new_key_and_retires_the_old_one(self):
        old_key = self.site.key
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), SITE_KEYS)
        self.assertNotEqual(response.data["key"], old_key)
        self.assertEqual(Site.objects.get(pk=self.site.pk).key, response.data["key"])
        self.assertFalse(Site.objects.filter(key=old_key).exists())
        old_lookup = self.client.get(f"{URL}?key={old_key}")
        self.assertEqual(old_lookup.data["results"], [])
        new_lookup = self.client.get(f"{URL}?key={response.data['key']}")
        self.assertEqual([item["id"] for item in new_lookup.data["results"]], [self.site.id])

    def test_rotating_keeps_the_other_settings(self):
        response = self.client.post(self.url)
        self.assertEqual(response.data["greeting"], "Hello")
        self.assertEqual(response.data["allowed_origins"], ["https://shop.example.com"])
        self.assertEqual(response.data["name"], self.site.name)

    def test_other_sites_keep_their_keys(self):
        other = SiteFactory()
        self.client.post(self.url)
        other.refresh_from_db()
        self.assertEqual(Site.objects.get(pk=other.pk).key, other.key)

    def test_an_inactive_site_can_be_rotated(self):
        Site.objects.filter(pk=self.site.pk).update(is_active=False)
        self.assertEqual(self.client.post(self.url).status_code, 200)

    def test_only_post_is_allowed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.data["error"]["code"], "method_not_allowed")

    def test_unknown_site_returns_404(self):
        response = self.client.post(f"{URL}999999/rotate-key/")
        self.assertEqual(response.status_code, 404)


class SiteSchemaTests(TestCase):
    def test_routes_are_documented_under_the_sites_tag(self):
        response = APIClient().get("/api/schema/?format=json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertEqual(paths["/api/sites/"]["get"]["tags"], ["Sites"])
        self.assertEqual(paths["/api/sites/"]["post"]["tags"], ["Sites"])
        self.assertEqual(paths["/api/sites/{id}/"]["get"]["tags"], ["Sites"])
        self.assertEqual(paths["/api/sites/{id}/"]["patch"]["tags"], ["Sites"])
        self.assertEqual(paths["/api/sites/{id}/rotate-key/"]["post"]["tags"], ["Sites"])
        self.assertNotIn("put", paths["/api/sites/{id}/"])
        self.assertNotIn("delete", paths["/api/sites/{id}/"])
