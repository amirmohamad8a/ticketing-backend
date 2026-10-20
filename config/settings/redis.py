from config.settings.environment import env

CACHE_REDIS_URL = env("CACHE_REDIS_URL", default="redis://localhost:6379/0")
BROKER_REDIS_URL = env("BROKER_REDIS_URL", default="redis://localhost:6379/1")
CHANNEL_REDIS_URL = env("CHANNEL_REDIS_URL", default="redis://localhost:6379/2")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": CACHE_REDIS_URL,
        "KEY_PREFIX": "ticketing",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [CHANNEL_REDIS_URL],
            "prefix": "ticketing",
        },
    }
}
