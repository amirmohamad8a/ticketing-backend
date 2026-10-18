import os
from functools import cached_property

from django.conf import settings
from django.core import signing
from django.core.files.storage import FileSystemStorage
from django.urls import reverse
from django.utils.http import content_disposition_header

import boto3
from botocore.config import Config
from storages.backends.s3 import S3Storage
from storages.utils import clean_name

from core.downloads import DOWNLOAD_SALT


def _download_response(url, ttl):
    return {"url": url, "expires_in": ttl}


class LocalStorage(FileSystemStorage):
    def download_link(self, request, file, content_type, filename=None):
        ttl = settings.DOWNLOAD_URL_TTL_SECONDS
        filename = filename or os.path.basename(file.name)
        token = signing.dumps(
            {"name": file.name, "content_type": content_type, "filename": filename},
            salt=DOWNLOAD_SALT,
            compress=True,
        )
        url = request.build_absolute_uri(reverse("signed-download", args=[token]))
        return _download_response(url, ttl)


class PresignedS3Storage(S3Storage):
    def __init__(self, **settings):
        self.public_endpoint_url = settings.pop("public_endpoint_url", None)
        super().__init__(**settings)

    @cached_property
    def public_client(self):
        return boto3.client(
            "s3",
            endpoint_url=self.public_endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region_name,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def url(self, name, parameters=None, expire=None, http_method=None):
        if not self.public_endpoint_url:
            return super().url(name, parameters, expire, http_method)
        params = dict(parameters or {})
        params["Bucket"] = self.bucket_name
        params["Key"] = self._normalize_name(clean_name(name))
        return self.public_client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expire if expire is not None else self.querystring_expire,
            HttpMethod=http_method,
        )

    def download_link(self, request, file, content_type, filename=None):
        ttl = settings.DOWNLOAD_URL_TTL_SECONDS
        filename = filename or os.path.basename(file.name)
        url = self.url(
            file.name,
            parameters={
                "ResponseContentType": content_type,
                "ResponseContentDisposition": content_disposition_header(True, filename),
            },
            expire=ttl,
        )
        return _download_response(url, ttl)
