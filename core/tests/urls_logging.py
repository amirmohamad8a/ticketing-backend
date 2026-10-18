import logging

from django.urls import path

from rest_framework.decorators import api_view
from rest_framework.response import Response

logger = logging.getLogger("core.tests.traced")


@api_view(["GET"])
def traced(request):
    logger.info("loading data")
    logger.info("rendering data")
    return Response({"ok": True})


@api_view(["GET"])
def broken(request):
    raise RuntimeError("boom")


urlpatterns = [
    path("traced/", traced),
    path("broken/", broken),
]
