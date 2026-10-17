import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter

from config.routing import websocket_urlpatterns
from core.middleware import BodySizeLimitASGI
from realtime.auth import TicketAuthMiddleware

application = BodySizeLimitASGI(
    ProtocolTypeRouter(
        {
            "http": django_asgi_app,
            "websocket": TicketAuthMiddleware(URLRouter(websocket_urlpatterns)),
        }
    )
)
