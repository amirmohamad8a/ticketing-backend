from django.contrib.postgres.search import SearchQuery, SearchVector
from django.db.models import Func, TextField, Value

SEARCH_CONFIG = "simple"
MAX_SEARCH_LENGTH = 100

ARABIC_YEH = "\u064a"
ARABIC_ALEF_MAKSURA = "\u0649"
ARABIC_KAF = "\u0643"
PERSIAN_YEH = "\u06cc"
PERSIAN_KAF = "\u06a9"
ZERO_WIDTH_NON_JOINER = "\u200c"
PERSIAN_DIGITS = "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"
ARABIC_INDIC_DIGITS = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
ASCII_DIGITS = "0123456789"

CHARACTER_MAP = {
    ARABIC_YEH: PERSIAN_YEH,
    ARABIC_ALEF_MAKSURA: PERSIAN_YEH,
    ARABIC_KAF: PERSIAN_KAF,
    ZERO_WIDTH_NON_JOINER: " ",
    **dict(zip(PERSIAN_DIGITS, ASCII_DIGITS)),
    **dict(zip(ARABIC_INDIC_DIGITS, ASCII_DIGITS)),
}

SOURCE_CHARACTERS = "".join(CHARACTER_MAP)
TARGET_CHARACTERS = "".join(CHARACTER_MAP.values())
TRANSLATION_TABLE = str.maketrans(CHARACTER_MAP)


class NormalizedText(Func):
    function = "translate"

    def __init__(self, expression, **extra):
        super().__init__(
            expression,
            Value(SOURCE_CHARACTERS),
            Value(TARGET_CHARACTERS),
            output_field=TextField(),
            **extra,
        )


def normalize_search_text(value):
    return " ".join(str(value).translate(TRANSLATION_TABLE).split())


def build_search_vector(*fields):
    return SearchVector(*(NormalizedText(field) for field in fields), config=SEARCH_CONFIG)


def build_search_query(term):
    return SearchQuery(normalize_search_text(term), config=SEARCH_CONFIG, search_type="websearch")
