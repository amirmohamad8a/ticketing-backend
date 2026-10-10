from drf_spectacular.utils import extend_schema, extend_schema_view

from tickets.serializers import TicketSerializer

ticket_schema = extend_schema_view(
    list=extend_schema(tags=["Tickets"]),
    retrieve=extend_schema(tags=["Tickets"]),
    create=extend_schema(tags=["Tickets"]),
    update=extend_schema(tags=["Tickets"]),
    partial_update=extend_schema(tags=["Tickets"]),
    destroy=extend_schema(tags=["Tickets"]),
    restore=extend_schema(tags=["Tickets"], request=None, responses=TicketSerializer),
    events=extend_schema(tags=["Tickets"]),
    comments=extend_schema(tags=["Tickets"]),
    attachments=extend_schema(tags=["Tickets"]),
)
