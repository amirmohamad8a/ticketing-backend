from corsheaders.defaults import default_headers

from config.settings.environment import env

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

MAX_REQUEST_BODY_BYTES = env.int("MAX_REQUEST_BODY_BYTES", default=64 * 1024)
MAX_UPLOAD_BODY_BYTES = env.int("MAX_UPLOAD_BODY_BYTES", default=11 * 1024 * 1024)
LOGIN_USERNAME_SLOWDOWN_SECONDS = env.float("LOGIN_USERNAME_SLOWDOWN_SECONDS", default=0.5)

ADMIN_LOGIN_PATH = "/admin/login/"
ADMIN_LOGIN_MAX_ATTEMPTS = env.int("ADMIN_LOGIN_MAX_ATTEMPTS", default=10)
ADMIN_LOGIN_WINDOW_SECONDS = env.int("ADMIN_LOGIN_WINDOW_SECONDS", default=300)

METRICS_TOKEN = env("METRICS_TOKEN", default="")

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_EXPOSE_HEADERS = ["X-Request-ID"]
CORS_ALLOW_HEADERS = (*default_headers, "x-visitor-token")
