from functools import cached_property

import boto3
from botocore.config import Config
from storages.backends.s3 import S3Storage
from storages.utils import clean_name


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
