from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from realtime.schema import socket_ticket_schema
from realtime.tickets import issue_ticket


@socket_ticket_schema
class SocketTicketView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ws_ticket"

    def post(self, request):
        return Response(issue_ticket(user=request.user))
