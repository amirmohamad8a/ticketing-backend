from datetime import timedelta

from django.contrib.admin.sites import site as admin_site
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from chat.models import Visitor
from core.tests.factories import SiteFactory, TicketFactory, VisitorFactory


class VisitorModelTests(TestCase):
    def test_defaults(self):
        visitor = Visitor.objects.create(site=SiteFactory())
        self.assertEqual(visitor.name, "")
        self.assertEqual(visitor.phone, "")
        self.assertEqual(visitor.email, "")
        self.assertIsNotNone(visitor.created_at)
        self.assertLess(timezone.now() - visitor.last_seen_at, timedelta(minutes=1))
        visitor.full_clean()

    def test_every_contact_detail_is_optional(self):
        Visitor(site=SiteFactory()).full_clean()
        Visitor(
            site=SiteFactory(), name="Sara", phone="09123456789", email="sara@example.com"
        ).full_clean()

    def test_a_site_is_required(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Visitor.objects.create()

    def test_invalid_phone_numbers_fail_validation(self):
        for phone in ("12345", "+989123456789", "0912345678", "abcdefghijk"):
            with self.subTest(phone=phone):
                with self.assertRaises(ValidationError) as caught:
                    Visitor(site=SiteFactory(), phone=phone).full_clean()
                self.assertIn("phone", caught.exception.message_dict)

    def test_invalid_email_fails_validation(self):
        with self.assertRaises(ValidationError) as caught:
            Visitor(site=SiteFactory(), email="not-an-email").full_clean()
        self.assertIn("email", caught.exception.message_dict)

    def test_overlong_name_fails_validation(self):
        with self.assertRaises(ValidationError) as caught:
            Visitor(site=SiteFactory(), name="x" * 101).full_clean()
        self.assertIn("name", caught.exception.message_dict)

    def test_persian_name_is_accepted(self):
        visitor = Visitor.objects.create(site=SiteFactory(), name="سارا احمدی")
        visitor.refresh_from_db()
        self.assertEqual(visitor.name, "سارا احمدی")

    def test_str_prefers_the_name_and_falls_back_to_the_id(self):
        named = VisitorFactory(name="Sara")
        anonymous = VisitorFactory(name="")
        self.assertEqual(str(named), "Sara")
        self.assertEqual(str(anonymous), f"Visitor #{anonymous.pk}")

    def test_visitors_are_ordered_by_id(self):
        first = VisitorFactory(name="Zeta")
        second = VisitorFactory(name="Alpha")
        self.assertEqual(list(Visitor.objects.all()), [first, second])

    def test_a_site_lists_its_visitors(self):
        site = SiteFactory()
        mine = VisitorFactory.create_batch(2, site=site)
        VisitorFactory()
        self.assertEqual(list(site.visitors.all()), mine)

    def test_last_seen_at_can_be_moved_forward(self):
        visitor = VisitorFactory()
        later = timezone.now() + timedelta(hours=1)
        visitor.last_seen_at = later
        visitor.save(update_fields=["last_seen_at"])
        visitor.refresh_from_db()
        self.assertEqual(visitor.last_seen_at, later)

    def test_factory_builds_a_valid_visitor(self):
        visitor = VisitorFactory()
        self.assertIsNotNone(visitor.site)
        visitor.full_clean()


class VisitorProtectionTests(TestCase):
    def test_a_site_with_visitors_cannot_be_deleted(self):
        visitor = VisitorFactory()
        with self.assertRaises(ProtectedError):
            visitor.site.delete()
        self.assertTrue(Visitor.objects.filter(pk=visitor.pk).exists())

    def test_a_visitor_with_tickets_cannot_be_deleted(self):
        ticket = TicketFactory(from_visitor=True)
        with self.assertRaises(ProtectedError):
            ticket.visitor.delete()
        self.assertTrue(Visitor.objects.filter(pk=ticket.visitor_id).exists())

    def test_a_visitor_with_only_a_deleted_ticket_is_still_protected(self):
        ticket = TicketFactory(from_visitor=True)
        ticket.delete()
        with self.assertRaises(ProtectedError):
            ticket.visitor.delete()

    def test_a_visitor_without_tickets_can_be_deleted(self):
        visitor = VisitorFactory()
        visitor.delete()
        self.assertFalse(Visitor.objects.filter(pk=visitor.pk).exists())


class VisitorAdminRegistrationTests(TestCase):
    def test_visitor_is_registered_in_the_admin(self):
        self.assertIn(Visitor, admin_site._registry)

    def test_visitors_are_searchable_by_contact_details(self):
        admin_instance = admin_site._registry[Visitor]
        for field in ("name", "phone", "email"):
            self.assertIn(field, admin_instance.search_fields)

    def test_list_display_includes_key_fields(self):
        admin_instance = admin_site._registry[Visitor]
        for field in ("site", "name", "last_seen_at"):
            self.assertIn(field, admin_instance.list_display)
