import ipaddress
import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

MAX_ORIGINS = 20
DEFAULT_PORTS = {"http": 80, "https": 443}

_ORIGIN = re.compile(r"(https?)://([^/?#@\s]+)", re.IGNORECASE)
_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_HOSTNAME = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def _invalid_origin():
    return ValidationError(
        _("Enter a valid origin such as https://example.com."), code="invalid_origin"
    )


def normalize_origin(value):
    if not isinstance(value, str):
        raise _invalid_origin()
    match = _ORIGIN.fullmatch(value.strip())
    if match is None:
        raise _invalid_origin()
    scheme = match.group(1).lower()
    try:
        parts = urlsplit(f"//{match.group(2)}")
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise _invalid_origin()
    if not host:
        raise _invalid_origin()
    if ":" in host:
        try:
            host = f"[{ipaddress.IPv6Address(host).compressed}]"
        except ValueError:
            raise _invalid_origin()
    elif not _HOSTNAME.fullmatch(host):
        raise _invalid_origin()
    if port is not None and port != DEFAULT_PORTS[scheme]:
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def validate_origin_list(value):
    if not isinstance(value, list):
        raise ValidationError(_("Allowed origins must be a list."), code="invalid_origins")
    if len(value) > MAX_ORIGINS:
        raise ValidationError(
            _("At most %(max)s origins are allowed."),
            code="too_many_origins",
            params={"max": MAX_ORIGINS},
        )
    for origin in value:
        if normalize_origin(origin) != origin:
            raise ValidationError(
                _("Origins must be written in their canonical form, such as https://example.com."),
                code="invalid_origin",
            )
    if len(set(value)) != len(value):
        raise ValidationError(_("Origins must be unique."), code="duplicate_origin")


def validate_hex_color(value):
    if not _HEX_COLOR.fullmatch(value):
        raise ValidationError(_("Enter a color in the form #rrggbb."), code="invalid_color")
