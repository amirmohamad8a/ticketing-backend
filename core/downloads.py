from django.conf import settings
from django.core import signing
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied

DOWNLOAD_SALT = "core.downloads"


def build_download_link(request, file, content_type, filename=None):
    return file.storage.download_link(request, file, content_type, filename)


def read_download_token(token):
    try:
        return signing.loads(
            token,
            salt=DOWNLOAD_SALT,
            max_age=settings.DOWNLOAD_URL_TTL_SECONDS,
        )
    except signing.BadSignature as exc:
        raise PermissionDenied(_("The download link is invalid or has expired.")) from exc
