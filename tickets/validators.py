import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.search import (
    ARABIC_ALEF_MAKSURA,
    ARABIC_KAF,
    ARABIC_YEH,
    PERSIAN_KAF,
    PERSIAN_YEH,
    normalize_search_text,
)

MAX_SHORTCUT_LENGTH = 32
MAX_BODY_LENGTH = 4000
MAX_TAG_NAME_LENGTH = 50
MAX_TICKET_TAGS = 10

_SHORTCUT = re.compile(r"[\w-]+")
_TAG_NAME_TABLE = str.maketrans(
    {
        ARABIC_YEH: PERSIAN_YEH,
        ARABIC_ALEF_MAKSURA: PERSIAN_YEH,
        ARABIC_KAF: PERSIAN_KAF,
    }
)


def normalize_shortcut(value):
    return normalize_search_text(str(value).strip().lstrip("/")).lower()


def validate_shortcut(value):
    if not _SHORTCUT.fullmatch(value) or normalize_shortcut(value) != value:
        raise ValidationError(
            _("Shortcuts may contain only lowercase letters, digits, hyphens and underscores."),
            code="invalid_shortcut",
        )


def normalize_tag_name(value):
    return " ".join(str(value).translate(_TAG_NAME_TABLE).split())
