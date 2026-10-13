from drf_spectacular.utils import extend_schema, extend_schema_view

from realtime.serializers import SocketTicketSerializer

socket_ticket_schema = extend_schema_view(
    post=extend_schema(
        tags=["Realtime"],
        request=None,
        responses=SocketTicketSerializer,
    )
)
