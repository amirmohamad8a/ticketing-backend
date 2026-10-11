from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

import pytest

from accounts.models import User
from accounts.validators import normalize_phone, validate_iranian_mobile

CANONICAL = "09123456789"

EQUIVALENT_FORMS = [
    "09123456789",
    "+989123456789",
    "+98 912 345 6789",
    "00989123456789",
    "989123456789",
    "9123456789",
    "0912 345 6789",
    "0912-345-6789",
    "(0912) 345 6789",
    "0912\u200c3456789",
    "  09123456789  ",
    "۰۹۱۲۳۴۵۶۷۸۹",
    "٠٩١٢٣٤٥٦٧٨٩",
    "+۹۸۹۱۲۳۴۵۶۷۸۹",
]

NOT_IRANIAN_MOBILES = [
    "",
    "12345",
    "08123456789",
    "0912345678",
    "091234567890",
    "abcdefghijk",
    "+982112345678",
    "0912345678a",
    "+989123456789012",
]


@pytest.mark.parametrize("raw", EQUIVALENT_FORMS)
def test_equivalent_forms_normalize_to_the_canonical_number(raw):
    assert normalize_phone(raw) == CANONICAL


@pytest.mark.parametrize("raw", ["09123456789", "09010000000", "09999999999"])
def test_validator_accepts_canonical_mobile_numbers(raw):
    validate_iranian_mobile(raw)


@pytest.mark.parametrize("raw", NOT_IRANIAN_MOBILES)
def test_numbers_that_are_not_iranian_mobiles_are_rejected(raw):
    with pytest.raises(ValidationError) as caught:
        validate_iranian_mobile(normalize_phone(raw))
    assert caught.value.code == "invalid_phone"


@pytest.mark.parametrize("raw", ["+989123456789", "9123456789", "۰۹۱۲۳۴۵۶۷۸۹", "0912 345 6789"])
def test_validator_does_not_normalize_its_input(raw):
    with pytest.raises(ValidationError):
        validate_iranian_mobile(raw)


class UserPhoneModelTests(TestCase):
    def _user(self, username, phone=None):
        return User(username=username, password="pass12345", phone=phone)

    def test_phone_is_optional(self):
        self._user("nophone").full_clean()
        self._user("blankphone", phone="").full_clean()

    def test_valid_phone_passes_full_clean(self):
        self._user("withphone", phone=CANONICAL).full_clean()

    def test_invalid_phone_fails_full_clean(self):
        with self.assertRaises(ValidationError) as caught:
            self._user("badphone", phone="12345").full_clean()
        self.assertIn("phone", caught.exception.message_dict)

    def test_non_canonical_phone_fails_full_clean(self):
        with self.assertRaises(ValidationError) as caught:
            self._user("rawphone", phone="+989123456789").full_clean()
        self.assertIn("phone", caught.exception.message_dict)

    def test_many_users_can_have_no_phone(self):
        User.objects.create_user(username="first", password="pass12345")
        User.objects.create_user(username="second", password="pass12345")
        self.assertEqual(User.objects.filter(phone__isnull=True).count(), 2)
        self._user("third").full_clean()

    def test_phone_must_be_unique(self):
        User.objects.create_user(username="owner", password="pass12345", phone=CANONICAL)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(username="copy", password="pass12345", phone=CANONICAL)
        with self.assertRaises(ValidationError) as caught:
            self._user("another", phone=CANONICAL).full_clean()
        self.assertIn("phone", caught.exception.message_dict)


class UserAdminPhoneTests(TestCase):
    def test_phone_is_listed_and_searchable_in_the_admin(self):
        admin_instance = site._registry[User]
        self.assertIn("phone", admin_instance.list_display)
        self.assertIn("phone", admin_instance.search_fields)
