from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import IsAgentOrAdmin
from chat.presence import online_agents
from core.tickets import issue_ticket
from realtime.schema import online_agents_schema, socket_ticket_schema
from realtime.serializers import OnlineAgentSerializer
from tickets.participants import Participant


@socket_ticket_schema
class SocketTicketView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ws_ticket"

    def post(self, request):
        return Response(issue_ticket(Participant(user=request.user)))


@online_agents_schema
class OnlineAgentsView(APIView):
    permission_classes = [IsAgentOrAdmin]

    def get(self, request):
        return Response(OnlineAgentSerializer(online_agents(), many=True).data)
