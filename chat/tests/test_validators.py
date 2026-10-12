from django.core.exceptions import ValidationError

import pytest

from chat.validators import MAX_ORIGINS, normalize_origin, validate_hex_color, validate_origin_list

NORMALIZED = [
    ("https://example.com", "https://example.com"),
    ("HTTPS://Example.COM", "https://example.com"),
    ("  https://example.com  ", "https://example.com"),
    ("https://example.com:443", "https://example.com"),
    ("http://example.com:80", "http://example.com"),
    ("http://example.com:443", "http://example.com:443"),
    ("https://example.com:80", "https://example.com:80"),
    ("http://localhost:3000", "http://localhost:3000"),
    ("https://shop.example.co.uk:8443", "https://shop.example.co.uk:8443"),
    ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
    ("http://[::1]:3000", "http://[::1]:3000"),
    ("http://[0:0:0:0:0:0:0:1]:3000", "http://[::1]:3000"),
]

INVALID_ORIGINS = [
    "",
    "   ",
    "*",
    "example.com",
    "//example.com",
    "ftp://example.com",
    "javascript:alert(1)",
    "https://",
    "https://example.com/",
    "https://example.com/path",
    "https://example.com?x=1",
    "https://example.com#top",
    "https://user@example.com",
    "https://exa mple.com",
    "https://*.example.com",
    "https://-bad.example.com",
    "https://exa_mple.com",
    "https://example.com:99999",
    "https://example.com:abc",
    "https://:80",
    "https://[::1",
    None,
    42,
]


@pytest.mark.parametrize("raw,expected", NORMALIZED)
def test_origins_are_normalized_to_their_canonical_form(raw, expected):
    assert normalize_origin(raw) == expected


@pytest.mark.parametrize("raw", INVALID_ORIGINS)
def test_invalid_origins_are_rejected(raw):
    with pytest.raises(ValidationError) as caught:
        normalize_origin(raw)
    assert caught.value.code == "invalid_origin"


@pytest.mark.parametrize("raw,expected", NORMALIZED)
def test_normalizing_twice_changes_nothing(raw, expected):
    assert normalize_origin(normalize_origin(raw)) == expected


@pytest.mark.parametrize(
    "value",
    [
        [],
        ["https://example.com"],
        ["https://a.example.com", "http://localhost:3000"],
        [f"https://site{index}.example.com" for index in range(MAX_ORIGINS)],
    ],
)
def test_canonical_origin_lists_are_accepted(value):
    validate_origin_list(value)


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com",
        None,
        {"origin": "https://example.com"},
        [1],
        [None],
        ["https://Example.com"],
        ["https://example.com/"],
        ["https://example.com:443"],
        ["https://example.com", "https://example.com"],
        [f"https://site{index}.example.com" for index in range(MAX_ORIGINS + 1)],
    ],
)
def test_origin_lists_that_are_not_canonical_are_rejected(value):
    with pytest.raises(ValidationError):
        validate_origin_list(value)


@pytest.mark.parametrize("value", ["#2563eb", "#ABCDEF", "#000000", "#fF00aA"])
def test_valid_hex_colors_are_accepted(value):
    validate_hex_color(value)


@pytest.mark.parametrize(
    "value", ["", "2563eb", "#fff", "#12345g", "#1234567", "red", "# 2563eb", "#2563eb "]
)
def test_invalid_hex_colors_are_rejected(value):
    with pytest.raises(ValidationError) as caught:
        validate_hex_color(value)
    assert caught.value.code == "invalid_color"
