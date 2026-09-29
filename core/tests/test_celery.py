from django.conf import settings

import pytest

from config import celery_app
from config.celery import app
from core.tasks import add


@pytest.fixture
def eager_tasks():
    previous = app.conf.task_always_eager
    app.conf.task_always_eager = True
    yield
    app.conf.task_always_eager = previous


def test_celery_app_is_exposed_by_config_package():
    assert celery_app is app


def test_broker_and_result_backend_use_redis_url():
    assert app.conf.broker_url == settings.REDIS_URL
    assert app.conf.result_backend == settings.REDIS_URL


def test_json_serialization_is_configured():
    assert app.conf.task_serializer == "json"
    assert app.conf.result_serializer == "json"
    assert list(app.conf.accept_content) == ["json"]


def test_add_task_runs_when_called_directly():
    assert add(2, 3) == 5


def test_add_task_delay_returns_result(eager_tasks):
    result = add.delay(2, 3)
    assert result.get() == 5


def test_add_task_apply_async_with_kwargs(eager_tasks):
    result = add.apply_async(kwargs={"x": 4, "y": 6})
    assert result.get() == 10
