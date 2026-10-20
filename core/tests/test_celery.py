from django.conf import settings
from django.core.validators import MaxValueValidator

from chat.models import Site
from config import celery_app
from config.celery import app


def test_celery_app_is_exposed_by_config_package():
    assert celery_app is app


def test_broker_and_result_backend_come_from_the_celery_settings():
    assert app.conf.broker_url == settings.CELERY_BROKER_URL
    assert app.conf.result_backend == settings.CELERY_RESULT_BACKEND


def test_json_serialization_is_configured():
    assert app.conf.task_serializer == "json"
    assert app.conf.result_serializer == "json"
    assert list(app.conf.accept_content) == ["json"]


def test_visibility_timeout_outlasts_the_longest_offline_countdown():
    field = Site._meta.get_field("offline_timeout_minutes")
    longest_seconds = (
        max(
            validator.limit_value
            for validator in field.validators
            if isinstance(validator, MaxValueValidator)
        )
        * 60
    )
    visibility_timeout = app.conf.broker_transport_options["visibility_timeout"]
    assert visibility_timeout > longest_seconds
