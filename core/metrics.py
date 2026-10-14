import logging
import os
import time

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from prometheus_client.core import GaugeMetricFamily

logger = logging.getLogger(__name__)

TICKETS_ENDPOINT = "tickets"
PRESENCE_ENDPOINT = "presence"
METRICS_PATH = "/metrics/"
UNMATCHED_VIEW = "unmatched"
OTHER_METHOD = "OTHER"
KNOWN_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

connected_sockets = Gauge(
    "ticketing_websocket_connections",
    "Open WebSocket connections.",
    ("endpoint", "client"),
    multiprocess_mode="livesum",
)

http_requests = Counter(
    "ticketing_http_requests_total",
    "HTTP requests handled, by method, view name and status code.",
    ("method", "view", "status"),
)

http_request_duration = Histogram(
    "ticketing_http_request_duration_seconds",
    "Time taken to produce an HTTP response, by method and view name.",
    ("method", "view"),
)


def socket_opened(endpoint, client):
    connected_sockets.labels(endpoint=endpoint, client=client).inc()


def socket_closed(endpoint, client):
    connected_sockets.labels(endpoint=endpoint, client=client).dec()


class RequestMetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == METRICS_PATH:
            return self.get_response(request)
        started = time.perf_counter()
        response = self.get_response(request)
        elapsed = time.perf_counter() - started
        match = request.resolver_match
        view = match.view_name if match is not None and match.view_name else UNMATCHED_VIEW
        method = request.method if request.method in KNOWN_METHODS else OTHER_METHOD
        http_requests.labels(method=method, view=view, status=str(response.status_code)).inc()
        http_request_duration.labels(method=method, view=view).observe(elapsed)
        return response


class DatabaseCollector:
    def collect(self):
        from stats.queries import queue_size

        try:
            size = queue_size()
        except Exception:
            logger.exception("Could not read the queue size for the metrics endpoint")
            return
        yield GaugeMetricFamily(
            "ticketing_queue_size",
            "Tickets without an assignee that are not resolved or closed.",
            value=size,
        )


_scrape_registry = CollectorRegistry()
_scrape_registry.register(DatabaseCollector())


def _is_multiprocess():
    return bool(
        os.environ.get("PROMETHEUS_MULTIPROC_DIR") or os.environ.get("prometheus_multiproc_dir")
    )


def render_metrics():
    if _is_multiprocess():
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = REGISTRY
    return generate_latest(registry) + generate_latest(_scrape_registry)
