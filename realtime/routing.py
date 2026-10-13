from django.urls import path

from realtime.consumers import RealtimeConsumer

websocket_urlpatterns = [
    path("ws/", RealtimeConsumer.as_asgi()),
]
