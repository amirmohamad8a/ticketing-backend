import base64
import json
from datetime import UTC, datetime

from django.test import SimpleTestCase

from audit.cursors import KINDS, MAX_ID, InvalidCursor, decode_cursor, encode_cursor

MOMENT = datetime(2026, 3, 10, 20, 30, 15, 123456, tzinfo=UTC)


def _raw(payload):
    return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


class CursorRoundTripTests(SimpleTestCase):
    def test_a_cursor_decodes_to_what_was_encoded(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                cursor = encode_cursor(MOMENT, kind, 42)
                self.assertEqual(decode_cursor(cursor), (MOMENT, kind, 42))

    def test_microseconds_are_kept(self):
        _moment, _kind, _id = decode_cursor(encode_cursor(MOMENT, "user", 1))
        self.assertEqual(_moment.microsecond, 123456)

    def test_the_largest_id_is_accepted(self):
        self.assertEqual(decode_cursor(encode_cursor(MOMENT, "ticket", MAX_ID))[2], MAX_ID)

    def test_a_cursor_is_url_safe_text(self):
        cursor = encode_cursor(MOMENT, "ticket", 7)
        self.assertRegex(cursor, r"^[A-Za-z0-9_=-]+$")


class InvalidCursorTests(SimpleTestCase):
    def _assert_invalid(self, value):
        with self.assertRaises(InvalidCursor):
            decode_cursor(value)

    def test_text_that_is_not_a_cursor_is_rejected(self):
        for value in ("", "garbage", "not base64!!", "é", "e30="):
            with self.subTest(value=value):
                self._assert_invalid(value)

    def test_payloads_of_the_wrong_shape_are_rejected(self):
        for payload in (
            {"a": 1},
            "text",
            5,
            None,
            [],
            ["2026-03-10T20:30:00+00:00", "ticket"],
            ["2026-03-10T20:30:00+00:00", "ticket", 1, 2],
        ):
            with self.subTest(payload=payload):
                self._assert_invalid(_raw(payload))

    def test_unknown_kinds_are_rejected(self):
        for kind in ("other", "", 5, None):
            with self.subTest(kind=kind):
                self._assert_invalid(_raw(["2026-03-10T20:30:00+00:00", kind, 1]))

    def test_invalid_ids_are_rejected(self):
        for row_id in (0, -1, True, "7", 1.5, None, MAX_ID + 1):
            with self.subTest(row_id=row_id):
                self._assert_invalid(_raw(["2026-03-10T20:30:00+00:00", "ticket", row_id]))

    def test_invalid_moments_are_rejected(self):
        for moment in (123, "yesterday", "2026-03-10T20:30:00", None):
            with self.subTest(moment=moment):
                self._assert_invalid(_raw([moment, "ticket", 1]))

    def test_deeply_nested_payloads_are_rejected(self):
        raw = base64.urlsafe_b64encode(b"[" * 100000).decode("ascii")
        self._assert_invalid(raw)
