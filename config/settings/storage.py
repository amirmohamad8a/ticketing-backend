from django.core.exceptions import ImproperlyConfigured

from config.settings.environment import BASE_DIR, env

STATIC_URL = "static/"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGE_BACKEND = env("STORAGE_BACKEND", default="local")
DOWNLOAD_URL_TTL_SECONDS = env.int("DOWNLOAD_URL_TTL_SECONDS", default=300)

if STORAGE_BACKEND == "local":
    _DEFAULT_STORAGE = {"BACKEND": "django.core.files.storage.FileSystemStorage"}
elif STORAGE_BACKEND == "s3":
    _DEFAULT_STORAGE = {
        "BACKEND": "core.storage.PresignedS3Storage",
        "OPTIONS": {
            "bucket_name": env("S3_BUCKET_NAME"),
            "access_key": env("S3_ACCESS_KEY"),
            "secret_key": env("S3_SECRET_KEY"),
            "endpoint_url": env("S3_ENDPOINT_URL", default=None),
            "public_endpoint_url": env("S3_PUBLIC_ENDPOINT_URL", default=None),
            "region_name": env("S3_REGION_NAME", default="us-east-1"),
            "signature_version": "s3v4",
            "addressing_style": "path",
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": DOWNLOAD_URL_TTL_SECONDS,
            "file_overwrite": False,
        },
    }
else:
    raise ImproperlyConfigured("STORAGE_BACKEND must be 'local' or 's3'.")

STORAGES = {
    "default": _DEFAULT_STORAGE,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
