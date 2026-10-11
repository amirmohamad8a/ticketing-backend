import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

PERSIAN_DIGITS = "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"
ARABIC_INDIC_DIGITS = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"

_DIGIT_TABLE = str.maketrans(PERSIAN_DIGITS + ARABIC_INDIC_DIGITS, "0123456789" * 2)
_IGNORED_CHARACTERS = re.compile(r"[\s\-().\u200c\u200e\u200f]")
_MOBILE_NUMBER = re.compile(r"09[0-9]{9}")


def normalize_phone(value):
    cleaned = _IGNORED_CHARACTERS.sub("", str(value).translate(_DIGIT_TABLE))
    if cleaned.startswith("+98"):
        return "0" + cleaned[3:]
    if cleaned.startswith("0098"):
        return "0" + cleaned[4:]
    if cleaned.startswith("98") and len(cleaned) == 12:
        return "0" + cleaned[2:]
    if cleaned.startswith("9") and len(cleaned) == 10:
        return "0" + cleaned
    return cleaned


def validate_iranian_mobile(value):
    if not _MOBILE_NUMBER.fullmatch(value):
        raise ValidationError(_("Enter a valid Iranian mobile number."), code="invalid_phone")
