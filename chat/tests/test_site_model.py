from django.contrib.admin.sites import site as admin_site
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from chat.models import Site
from core.tests.factories import SiteFactory


class SiteModelTests(TestCase):
    def test_defaults(self):
        created = Site.objects.create(name="Shop")
        self.assertEqual(created.allowed_origins, [])
        self.assertTrue(created.is_active)
        self.assertEqual(created.greeting, "")
        self.assertEqual(created.primary_color, "#2563eb")
        self.assertEqual(created.position, Site.Position.BOTTOM_RIGHT)
        self.assertEqual(created.offline_timeout_minutes, 5)
        self.assertFalse(created.require_name)
        self.assertFalse(created.require_contact)
        self.assertIsNotNone(created.created_at)
        self.assertIsNotNone(created.updated_at)
        created.full_clean()

    def test_key_is_generated_url_safe_and_long(self):
        created = Site.objects.create(name="Shop")
        self.assertRegex(created.key, r"^[A-Za-z0-9_-]{32}$")

    def test_keys_are_unique_across_sites(self):
        keys = {Site.objects.create(name=f"Shop {index}").key for index in range(20)}
        self.assertEqual(len(keys), 20)

    def test_the_database_rejects_a_duplicate_key(self):
        first = Site.objects.create(name="First")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Site.objects.create(name="Second", key=first.key)

    def test_key_is_not_editable(self):
        self.assertFalse(Site._meta.get_field("key").editable)

    def test_str_returns_the_name(self):
        self.assertEqual(str(Site(name="Shop")), "Shop")

    def test_sites_are_ordered_by_id(self):
        first = SiteFactory(name="Zeta")
        second = SiteFactory(name="Alpha")
        self.assertEqual(list(Site.objects.all()), [first, second])

    def test_factory_builds_a_valid_site(self):
        created = SiteFactory()
        self.assertEqual(created.allowed_origins, ["https://example.com"])
        created.full_clean()

    def test_updated_at_changes_on_save(self):
        created = SiteFactory()
        before = created.updated_at
        created.name = "Renamed"
        created.save()
        created.refresh_from_db()
        self.assertGreater(created.updated_at, before)

    def test_rotating_replaces_the_key_and_keeps_everything_else(self):
        created = SiteFactory(greeting="Hello", require_name=True)
        old_key = created.key
        before = created.updated_at
        created.rotate_key()
        stored = Site.objects.get(pk=created.pk)
        self.assertNotEqual(stored.key, old_key)
        self.assertEqual(stored.key, created.key)
        self.assertRegex(stored.key, r"^[A-Za-z0-9_-]{32}$")
        self.assertEqual(stored.greeting, "Hello")
        self.assertTrue(stored.require_name)
        self.assertGreater(stored.updated_at, before)
        self.assertFalse(Site.objects.filter(key=old_key).exists())


class SiteValidationTests(TestCase):
    def _site(self, **overrides):
        return Site(name="Shop", **overrides)

    def _assert_invalid(self, field, **overrides):
        with self.assertRaises(ValidationError) as caught:
            self._site(**overrides).full_clean()
        self.assertIn(field, caught.exception.message_dict)

    def test_valid_origins_pass(self):
        self._site(allowed_origins=["https://example.com", "http://localhost:3000"]).full_clean()

    def test_invalid_origins_fail(self):
        for origins in (
            ["example.com"],
            ["https://example.com/"],
            ["https://Example.com"],
            ["https://example.com", "https://example.com"],
            "https://example.com",
        ):
            with self.subTest(origins=origins):
                self._assert_invalid("allowed_origins", allowed_origins=origins)

    def test_invalid_colors_fail(self):
        for color in ("red", "#fff", "2563eb", "#12345g"):
            with self.subTest(color=color):
                self._assert_invalid("primary_color", primary_color=color)

    def test_valid_colors_pass(self):
        self._site(primary_color="#FFaa00").full_clean()

    def test_unknown_position_fails(self):
        self._assert_invalid("position", position="top")

    def test_every_position_passes(self):
        for position in Site.Position.values:
            with self.subTest(position=position):
                self._site(position=position).full_clean()

    def test_timeout_must_be_between_one_minute_and_one_day(self):
        for minutes in (0, 1441):
            with self.subTest(minutes=minutes):
                self._assert_invalid("offline_timeout_minutes", offline_timeout_minutes=minutes)
        for minutes in (1, 1440):
            with self.subTest(minutes=minutes):
                self._site(offline_timeout_minutes=minutes).full_clean()

    def test_name_is_required(self):
        with self.assertRaises(ValidationError) as caught:
            Site(name="").full_clean()
        self.assertIn("name", caught.exception.message_dict)


class SiteAdminRegistrationTests(TestCase):
    def test_site_is_registered_in_the_admin(self):
        self.assertIn(Site, admin_site._registry)

    def test_key_and_timestamps_are_read_only(self):
        admin_instance = admin_site._registry[Site]
        for field in ("key", "created_at", "updated_at"):
            self.assertIn(field, admin_instance.readonly_fields)

    def test_list_display_includes_key_fields(self):
        admin_instance = admin_site._registry[Site]
        for field in ("name", "key", "is_active"):
            self.assertIn(field, admin_instance.list_display)
