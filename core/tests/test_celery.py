from django.conf import settings

from config import celery_app
from config.celery import app


def test_celery_app_is_exposed_by_config_package():
    assert celery_app is app


def test_broker_and_result_backend_use_redis_url():
    assert app.conf.broker_url == settings.REDIS_URL
    assert app.conf.result_backend == settings.REDIS_URL


def test_json_serialization_is_configured():
    assert app.conf.task_serializer == "json"
    assert app.conf.result_serializer == "json"
    assert list(app.conf.accept_content) == ["json"]
