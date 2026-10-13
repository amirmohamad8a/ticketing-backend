import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.search import normalize_search_text

MAX_SHORTCUT_LENGTH = 32
MAX_BODY_LENGTH = 4000

_SHORTCUT = re.compile(r"[\w-]+")


def normalize_shortcut(value):
    return normalize_search_text(str(value).strip().lstrip("/")).lower()


def validate_shortcut(value):
    if not _SHORTCUT.fullmatch(value) or normalize_shortcut(value) != value:
        raise ValidationError(
            _("Shortcuts may contain only lowercase letters, digits, hyphens and underscores."),
            code="invalid_shortcut",
        )
