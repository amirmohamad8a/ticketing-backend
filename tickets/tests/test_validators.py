from django.core.exceptions import ValidationError

import pytest

from core.search import ARABIC_KAF, ARABIC_YEH, PERSIAN_KAF, PERSIAN_YEH
from tickets.validators import normalize_shortcut, normalize_tag_name, validate_shortcut

NORMALIZED_SHORTCUTS = [
    ("greeting", "greeting"),
    ("/greeting", "greeting"),
    ("//Greeting", "greeting"),
    ("  /Hello  ", "hello"),
    ("HELLO", "hello"),
    ("a  b", "a b"),
    (f"a{ARABIC_YEH}", f"a{PERSIAN_YEH}"),
    ("\u06f1\u06f2", "12"),
    ("\u0661\u0662", "12"),
]

VALID_SHORTCUTS = ["greeting", "a-b", "a_b", "x1", "\u06a9\u062f1", "refund-policy"]

INVALID_SHORTCUTS = [
    "Greeting",
    "a b",
    "",
    "a/b",
    "a!",
    f"a{ARABIC_YEH}",
    "\u06f1",
]

NORMALIZED_TAG_NAMES = [
    ("bug", "bug"),
    ("  Bug   report ", "Bug report"),
    ("Bug\nreport", "Bug report"),
    (f"{ARABIC_YEH}{ARABIC_KAF}", f"{PERSIAN_YEH}{PERSIAN_KAF}"),
    (
        "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645",
        "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645",
    ),
    ("\u06f1", "\u06f1"),
    ("", ""),
]


@pytest.mark.parametrize("raw,expected", NORMALIZED_SHORTCUTS)
def test_shortcuts_are_normalized(raw, expected):
    assert normalize_shortcut(raw) == expected


@pytest.mark.parametrize("raw,expected", NORMALIZED_SHORTCUTS)
def test_normalizing_a_shortcut_twice_changes_nothing(raw, expected):
    assert normalize_shortcut(normalize_shortcut(raw)) == expected


@pytest.mark.parametrize("value", VALID_SHORTCUTS)
def test_valid_shortcuts_are_accepted(value):
    validate_shortcut(value)


@pytest.mark.parametrize("value", INVALID_SHORTCUTS)
def test_invalid_shortcuts_are_rejected(value):
    with pytest.raises(ValidationError) as caught:
        validate_shortcut(value)
    assert caught.value.code == "invalid_shortcut"


@pytest.mark.parametrize("raw,expected", NORMALIZED_TAG_NAMES)
def test_tag_names_are_normalized(raw, expected):
    assert normalize_tag_name(raw) == expected
