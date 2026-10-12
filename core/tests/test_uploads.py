import io
import zipfile
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from rest_framework.exceptions import ValidationError

from core.uploads import (
    DOCX_CONTENT_TYPE,
    HEAD_SIZE,
    MAX_NAME_LENGTH,
    ZIP_CONTENT_TYPE,
    clean_file_name,
    detect_content_type,
    ensure_content_matches,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF_BYTES = b"GIF89a" + b"\x00" * 32
PDF_BYTES = b"%PDF-1.4\n%%EOF"
SCRIPT_BYTES = b"#!/bin/sh\necho hello\n"


def _zip_bytes(*names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "content")
    return buffer.getvalue()


DOCX_BYTES = _zip_bytes("[Content_Types].xml", "word/document.xml")
ZIP_BYTES = _zip_bytes("notes.txt", "photos/cat.png")


def _upload(content, name="upload.bin", content_type="application/octet-stream"):
    return SimpleUploadedFile(name, content, content_type=content_type)


class DetectContentTypeTests(SimpleTestCase):
    def test_images_and_pdf_are_recognised_by_their_magic_bytes(self):
        samples = [
            (PNG_BYTES, "image/png"),
            (JPEG_BYTES, "image/jpeg"),
            (GIF_BYTES, "image/gif"),
            (PDF_BYTES, "application/pdf"),
        ]
        for content, expected in samples:
            with self.subTest(expected=expected):
                self.assertEqual(detect_content_type(_upload(content)), expected)

    def test_the_uploaded_name_and_declared_type_are_ignored(self):
        upload = _upload(PNG_BYTES, name="payload.sh", content_type="application/x-sh")
        self.assertEqual(detect_content_type(upload), "image/png")

    def test_plain_text_is_recognised_including_persian(self):
        for content in (b"hello world", SCRIPT_BYTES, "سلام دنیا".encode()):
            with self.subTest(content=content):
                self.assertEqual(detect_content_type(_upload(content)), "text/plain")

    def test_text_cut_in_the_middle_of_a_character_is_still_text(self):
        content = ("a" + "س" * HEAD_SIZE).encode()
        self.assertGreater(len(content), HEAD_SIZE)
        self.assertEqual(detect_content_type(_upload(content)), "text/plain")

    def test_binary_content_with_no_known_signature_is_not_recognised(self):
        for content in (b"abc\x00def", b"plain start \xff\xfe\xfd"):
            with self.subTest(content=content):
                self.assertIsNone(detect_content_type(_upload(content)))

    def test_empty_content_is_not_recognised(self):
        self.assertIsNone(detect_content_type(_upload(b"")))

    def test_docx_and_plain_zip_are_told_apart(self):
        self.assertEqual(detect_content_type(_upload(DOCX_BYTES)), DOCX_CONTENT_TYPE)
        self.assertEqual(detect_content_type(_upload(ZIP_BYTES)), ZIP_CONTENT_TYPE)

    def test_other_office_packages_are_plain_archives(self):
        content = _zip_bytes("[Content_Types].xml", "xl/workbook.xml")
        self.assertEqual(detect_content_type(_upload(content)), ZIP_CONTENT_TYPE)

    def test_truncated_or_corrupt_zip_is_not_recognised(self):
        self.assertIsNone(detect_content_type(_upload(b"PK\x03\x04" + b"not really a zip")))
        self.assertIsNone(detect_content_type(_upload(ZIP_BYTES[: len(ZIP_BYTES) // 2])))

    def test_archives_are_never_extracted_or_decompressed(self):
        refuse = Mock(side_effect=AssertionError("archive content must not be read"))
        with patch.multiple(
            zipfile.ZipFile, extract=refuse, extractall=refuse, read=refuse, open=refuse
        ):
            self.assertEqual(detect_content_type(_upload(DOCX_BYTES)), DOCX_CONTENT_TYPE)
            self.assertEqual(detect_content_type(_upload(ZIP_BYTES)), ZIP_CONTENT_TYPE)

    def test_the_file_is_rewound_after_detection(self):
        for content in (PNG_BYTES, DOCX_BYTES, b"hello"):
            with self.subTest(size=len(content)):
                upload = _upload(content)
                detect_content_type(upload)
                self.assertEqual(upload.tell(), 0)
                self.assertEqual(upload.read(), content)


class EnsureContentMatchesTests(SimpleTestCase):
    def test_matching_content_passes(self):
        ensure_content_matches(_upload(PNG_BYTES), "image/png")
        ensure_content_matches(_upload(b"hello"), "text/plain")
        ensure_content_matches(_upload(DOCX_BYTES), DOCX_CONTENT_TYPE)
        ensure_content_matches(_upload(ZIP_BYTES), ZIP_CONTENT_TYPE)

    def test_shell_script_declared_as_png_is_rejected(self):
        with self.assertRaises(ValidationError):
            ensure_content_matches(_upload(SCRIPT_BYTES, name="photo.png"), "image/png")

    def test_png_declared_as_pdf_is_rejected(self):
        with self.assertRaises(ValidationError):
            ensure_content_matches(_upload(PNG_BYTES), "application/pdf")

    def test_docx_and_zip_cannot_pass_for_each_other(self):
        with self.assertRaises(ValidationError):
            ensure_content_matches(_upload(DOCX_BYTES), ZIP_CONTENT_TYPE)
        with self.assertRaises(ValidationError):
            ensure_content_matches(_upload(ZIP_BYTES), DOCX_CONTENT_TYPE)

    def test_unrecognised_content_is_rejected(self):
        with self.assertRaises(ValidationError):
            ensure_content_matches(_upload(b"abc\x00def"), "text/plain")


class CleanFileNameTests(SimpleTestCase):
    def test_plain_names_are_kept(self):
        self.assertEqual(clean_file_name("report 2026.pdf"), "report 2026.pdf")
        self.assertEqual(clean_file_name("گزارش.txt"), "گزارش.txt")

    def test_directories_are_dropped(self):
        self.assertEqual(clean_file_name("../../etc/passwd"), "passwd")
        self.assertEqual(clean_file_name("C:\\Users\\me\\note.txt"), "note.txt")

    def test_control_characters_are_removed(self):
        self.assertEqual(clean_file_name("a\r\nb\x00.txt"), "ab.txt")

    def test_long_names_are_truncated(self):
        self.assertEqual(len(clean_file_name("a" * 400)), MAX_NAME_LENGTH)
