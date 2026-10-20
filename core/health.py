import asyncio
import logging
import threading
import time
import uuid

from django.core.cache import cache
from django.db import connection

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 3
CACHE_KEY_PREFIX = "ready-probe:"
CACHE_PROBE_TTL_SECONDS = 10
CHANNEL_PROBE_TYPE = "ready.probe"
RESULTS_TTL_SECONDS = 5
OK = "ok"
ERROR = "error"

_results_lock = threading.Lock()
_cached_results = None
_cached_at = 0.0


def check_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
    if row is None or row[0] != 1:
        raise RuntimeError("The database returned an unexpected answer.")


def check_cache():
    token = uuid.uuid4().hex
    key = f"{CACHE_KEY_PREFIX}{token}"
    cache.set(key, token, timeout=CACHE_PROBE_TTL_SECONDS)
    if cache.get(key) != token:
        raise RuntimeError("The cache did not return the stored value.")
    cache.delete(key)


async def _probe_layer(layer):
    channel = await layer.new_channel()
    await layer.send(channel, {"type": CHANNEL_PROBE_TYPE})
    message = await layer.receive(channel)
    if message.get("type") != CHANNEL_PROBE_TYPE:
        raise RuntimeError("The channel layer returned an unexpected message.")


async def _bounded_probe(layer):
    await asyncio.wait_for(_probe_layer(layer), timeout=CHECK_TIMEOUT_SECONDS)


def check_channel_layer():
    layer = get_channel_layer()
    if layer is None:
        raise RuntimeError("No channel layer is configured.")
    async_to_sync(_bounded_probe)(layer)


CHECKS = (
    ("database", check_database),
    ("cache", check_cache),
    ("channel_layer", check_channel_layer),
)


def run_checks():
    results = {}
    for name, check in CHECKS:
        try:
            check()
        except Exception:
            logger.warning("Readiness check failed", extra={"check": name}, exc_info=True)
            results[name] = ERROR
        else:
            results[name] = OK
    return results


def cached_run_checks():
    global _cached_results, _cached_at
    with _results_lock:
        now = time.monotonic()
        if _cached_results is None or now - _cached_at >= RESULTS_TTL_SECONDS:
            _cached_results = run_checks()
            _cached_at = now
        return dict(_cached_results)


def clear_cached_checks():
    global _cached_results, _cached_at
    with _results_lock:
        _cached_results = None
        _cached_at = 0.0


def all_passed(results):
    return all(status == OK for status in results.values())
