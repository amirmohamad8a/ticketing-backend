from django.urls import path

from realtime.views import SocketTicketView

urlpatterns = [
    path("ws/ticket/", SocketTicketView.as_view(), name="ws-ticket"),
]
