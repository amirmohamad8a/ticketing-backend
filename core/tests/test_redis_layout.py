from urllib.parse import urlsplit

from django.test import SimpleTestCase

from config.settings import celery as celery_settings
from config.settings import redis as redis_settings


def _database(url):
    return urlsplit(url).path.lstrip("/")


class RedisLayoutTests(SimpleTestCase):
    def test_cache_broker_and_channel_layer_use_separate_databases(self):
        databases = {
            _database(redis_settings.CACHE_REDIS_URL),
            _database(redis_settings.BROKER_REDIS_URL),
            _database(redis_settings.CHANNEL_REDIS_URL),
        }
        self.assertEqual(len(databases), 3)

    def test_the_cache_uses_its_own_url(self):
        self.assertEqual(
            redis_settings.CACHES["default"]["LOCATION"], redis_settings.CACHE_REDIS_URL
        )

    def test_the_channel_layer_uses_its_own_url(self):
        config = redis_settings.CHANNEL_LAYERS["default"]["CONFIG"]
        self.assertEqual(config["hosts"], [redis_settings.CHANNEL_REDIS_URL])

    def test_celery_broker_and_results_use_the_broker_url(self):
        self.assertEqual(celery_settings.CELERY_BROKER_URL, redis_settings.BROKER_REDIS_URL)
        self.assertEqual(celery_settings.CELERY_RESULT_BACKEND, redis_settings.BROKER_REDIS_URL)
