from django.urls import path

from realtime.views import OnlineAgentsView, SocketTicketView

urlpatterns = [
    path("ws/ticket/", SocketTicketView.as_view(), name="ws-ticket"),
    path("agents/online/", OnlineAgentsView.as_view(), name="agent-online-list"),
]
