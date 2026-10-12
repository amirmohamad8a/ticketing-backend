import codecs
import os
import zipfile

from django.utils.translation import gettext_lazy as _

import filetype
from rest_framework.exceptions import ValidationError

HEAD_SIZE = 8192
MAX_NAME_LENGTH = 255
TEXT_CONTENT_TYPE = "text/plain"
ZIP_CONTENT_TYPE = "application/zip"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ZIP_SIGNATURE = b"PK\x03\x04"
OOXML_MANIFEST = "[Content_Types].xml"
DOCX_MAIN_PART = "word/document.xml"


def _read_head(upload):
    upload.seek(0)
    head = upload.read(HEAD_SIZE)
    upload.seek(0)
    return head


def _classify_zip(upload):
    try:
        with zipfile.ZipFile(upload) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    finally:
        upload.seek(0)
    if OOXML_MANIFEST in names and DOCX_MAIN_PART in names:
        return DOCX_CONTENT_TYPE
    return ZIP_CONTENT_TYPE


def _is_text(head):
    if b"\x00" in head:
        return False
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(head)
    except UnicodeDecodeError:
        return False
    return True


def detect_content_type(upload):
    head = _read_head(upload)
    if not head:
        return None
    if head.startswith(ZIP_SIGNATURE):
        return _classify_zip(upload)
    detected = filetype.guess_mime(head)
    if detected is not None:
        return detected
    if _is_text(head):
        return TEXT_CONTENT_TYPE
    return None


def ensure_content_matches(upload, declared_content_type):
    if detect_content_type(upload) != declared_content_type:
        raise ValidationError(_("The file content does not match its declared type."))


def clean_file_name(name):
    base = os.path.basename(str(name).replace("\\", "/"))
    printable = "".join(char for char in base if char.isprintable())
    return printable[:MAX_NAME_LENGTH]
