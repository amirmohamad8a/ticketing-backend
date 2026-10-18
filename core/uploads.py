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


class UploadPolicy:
    def __init__(
        self,
        *,
        max_size_bytes,
        content_type_extensions,
        size_message,
        type_message,
        extensions=None,
        rename=None,
    ):
        self.max_size_bytes = max_size_bytes
        self.content_type_extensions = dict(content_type_extensions)
        self.allowed_content_types = frozenset(content_type_extensions)
        self.extensions = frozenset(extensions or content_type_extensions.values())
        self.size_message = size_message
        self.type_message = type_message
        self.rename = rename

    def validate(self, value, max_size_bytes=None):
        max_size_bytes = self.max_size_bytes if max_size_bytes is None else max_size_bytes
        if value.size > max_size_bytes:
            max_mb = max_size_bytes // (1024 * 1024)
            raise ValidationError(self.size_message % {"max_mb": max_mb})
        content_type = getattr(value, "content_type", "") or ""
        extension = self.content_type_extensions.get(content_type)
        if extension is None:
            raise ValidationError(self.type_message % {"content_type": content_type})
        ensure_content_matches(value, content_type)
        if self.rename is not None:
            value.name = self.rename(extension)
        return value


ATTACHMENT_UPLOAD_POLICY = UploadPolicy(
    max_size_bytes=10 * 1024 * 1024,
    content_type_extensions={
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/zip": ".zip",
    },
    size_message=_("File too large. Max size is %(max_mb)sMB."),
    type_message=_("File type '%(content_type)s' is not allowed."),
)

AVATAR_UPLOAD_POLICY = UploadPolicy(
    max_size_bytes=2 * 1024 * 1024,
    content_type_extensions={
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    },
    size_message=_("Avatar too large. Max size is %(max_mb)sMB."),
    type_message=_("Avatar must be a PNG, JPEG or WebP image."),
    extensions={".png", ".jpg", ".jpeg", ".webp"},
    rename=lambda extension: f"avatar{extension}",
)
