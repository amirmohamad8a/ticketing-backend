from django.test import SimpleTestCase
from django.utils.translation import gettext_lazy

from core.errors import DomainValidationError
from core.exceptions import custom_exception_handler


class DomainValidationErrorShapeTests(SimpleTestCase):
    def test_a_bare_string_becomes_a_list_of_one_message(self):
        exc = DomainValidationError({"name": "This field is required."})
        self.assertEqual(exc.details, {"name": ["This field is required."]})

    def test_a_lazy_translation_becomes_a_plain_string_in_a_list(self):
        exc = DomainValidationError(
            {"phone": gettext_lazy("A user with that phone number already exists.")}
        )
        self.assertEqual(exc.details, {"phone": ["A user with that phone number already exists."]})
        self.assertIsInstance(exc.details["phone"][0], str)

    def test_a_tuple_becomes_a_list(self):
        exc = DomainValidationError({"tags": ("first", "second")})
        self.assertEqual(exc.details, {"tags": ["first", "second"]})

    def test_a_list_is_kept_as_a_list(self):
        exc = DomainValidationError({"status": ["Cannot transition."]})
        self.assertEqual(exc.details, {"status": ["Cannot transition."]})

    def test_details_and_field_errors_are_the_same_normalized_dict(self):
        exc = DomainValidationError({"name": "x"})
        self.assertEqual(exc.details, exc.field_errors)

    def test_the_handler_returns_the_normalized_details(self):
        response = custom_exception_handler(DomainValidationError({"refresh": "Required."}), {})
        self.assertEqual(response.data["error"]["details"], {"refresh": ["Required."]})

    def test_no_field_errors_gives_empty_details(self):
        self.assertEqual(DomainValidationError().details, {})
