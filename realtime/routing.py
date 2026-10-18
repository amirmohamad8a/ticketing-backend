from django.urls import path

from realtime.consumers import RealtimeConsumer
from realtime.presence_consumer import PresenceConsumer

websocket_urlpatterns = [
    path("ws/", RealtimeConsumer.as_asgi()),
    path("ws/presence/", PresenceConsumer.as_asgi()),
]
