from django.test import SimpleTestCase

from core.search import (
    ARABIC_ALEF_MAKSURA,
    ARABIC_KAF,
    ARABIC_YEH,
    CHARACTER_MAP,
    MAX_SEARCH_LENGTH,
    PERSIAN_KAF,
    PERSIAN_YEH,
    SOURCE_CHARACTERS,
    TARGET_CHARACTERS,
    normalize_search_text,
)

ARABIC_NAME = f"\u0639\u0644{ARABIC_YEH}"
PERSIAN_NAME = f"\u0639\u0644{PERSIAN_YEH}"


class NormalizeSearchTextTests(SimpleTestCase):
    def test_arabic_yeh_becomes_persian_yeh(self):
        self.assertEqual(normalize_search_text(ARABIC_NAME), PERSIAN_NAME)

    def test_alef_maksura_becomes_persian_yeh(self):
        text = f"\u0645\u0648\u0633{ARABIC_ALEF_MAKSURA}"
        self.assertEqual(normalize_search_text(text), f"\u0645\u0648\u0633{PERSIAN_YEH}")

    def test_arabic_kaf_becomes_persian_kaf(self):
        text = f"{ARABIC_KAF}\u062a\u0627\u0628"
        self.assertEqual(normalize_search_text(text), f"{PERSIAN_KAF}\u062a\u0627\u0628")

    def test_persian_digits_become_ascii(self):
        self.assertEqual(
            normalize_search_text("\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9\u06f0"),
            "1234567890",
        )

    def test_arabic_indic_digits_become_ascii(self):
        self.assertEqual(
            normalize_search_text("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"),
            "0123456789",
        )

    def test_zero_width_non_joiner_becomes_a_space(self):
        text = "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"
        self.assertEqual(normalize_search_text(text), "\u0645\u06cc \u062e\u0648\u0627\u0647\u0645")

    def test_whitespace_is_collapsed_and_trimmed(self):
        self.assertEqual(normalize_search_text("  a \t b\n c  "), "a b c")

    def test_plain_text_is_left_alone(self):
        self.assertEqual(
            normalize_search_text("hello \u0633\u0644\u0627\u0645 42"),
            "hello \u0633\u0644\u0627\u0645 42",
        )

    def test_a_term_made_only_of_joiners_becomes_empty(self):
        self.assertEqual(normalize_search_text("\u200c\u200c"), "")

    def test_non_strings_are_converted(self):
        self.assertEqual(normalize_search_text(123), "123")

    def test_normalizing_twice_changes_nothing(self):
        once = normalize_search_text(f"{ARABIC_NAME}\u06f1 \u200c {ARABIC_KAF}")
        self.assertEqual(normalize_search_text(once), once)

    def test_source_and_target_alphabets_line_up_for_the_sql_translate(self):
        self.assertEqual(len(SOURCE_CHARACTERS), len(TARGET_CHARACTERS))
        self.assertEqual(len(SOURCE_CHARACTERS), len(CHARACTER_MAP))

    def test_the_maximum_search_length_is_one_hundred(self):
        self.assertEqual(MAX_SEARCH_LENGTH, 100)
