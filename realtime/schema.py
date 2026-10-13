from drf_spectacular.utils import extend_schema, extend_schema_view

from realtime.serializers import OnlineAgentSerializer, SocketTicketSerializer

socket_ticket_schema = extend_schema_view(
    post=extend_schema(
        tags=["Realtime"],
        request=None,
        responses=SocketTicketSerializer,
    )
)

online_agents_schema = extend_schema_view(
    get=extend_schema(
        tags=["Agents"],
        responses=OnlineAgentSerializer(many=True),
    )
)
