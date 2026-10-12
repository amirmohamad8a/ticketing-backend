import os

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import PermissionDenied

DOWNLOAD_SALT = "core.downloads"


def build_download_link(request, file, content_type, filename=None):
    ttl = settings.DOWNLOAD_URL_TTL_SECONDS
    filename = filename or os.path.basename(file.name)
    if settings.STORAGE_BACKEND == "s3":
        url = file.storage.url(
            file.name,
            parameters={
                "ResponseContentType": content_type,
                "ResponseContentDisposition": content_disposition_header(True, filename),
            },
            expire=ttl,
        )
    else:
        token = signing.dumps(
            {"name": file.name, "content_type": content_type, "filename": filename},
            salt=DOWNLOAD_SALT,
            compress=True,
        )
        url = request.build_absolute_uri(reverse("signed-download", args=[token]))
    return {"url": url, "expires_in": ttl}


def read_download_token(token):
    try:
        return signing.loads(
            token,
            salt=DOWNLOAD_SALT,
            max_age=settings.DOWNLOAD_URL_TTL_SECONDS,
        )
    except signing.BadSignature:
        raise PermissionDenied(_("The download link is invalid or has expired."))
