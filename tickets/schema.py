from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view

from core.serializers import DownloadLinkSerializer
from tickets.serializers import (
    MessageListSerializer,
    ReadMarkSerializer,
    ReadStateSerializer,
    TicketSerializer,
)

ticket_schema = extend_schema_view(
    list=extend_schema(tags=["Tickets"]),
    retrieve=extend_schema(tags=["Tickets"]),
    create=extend_schema(tags=["Tickets"]),
    update=extend_schema(tags=["Tickets"]),
    partial_update=extend_schema(tags=["Tickets"]),
    destroy=extend_schema(tags=["Tickets"]),
    restore=extend_schema(tags=["Tickets"], request=None, responses=TicketSerializer),
    claim=extend_schema(tags=["Tickets"], request=None, responses=TicketSerializer),
    mark_read=extend_schema(
        tags=["Tickets"],
        request=ReadMarkSerializer,
        responses=ReadStateSerializer,
    ),
    messages=extend_schema(
        tags=["Tickets"],
        parameters=[OpenApiParameter("after", int, OpenApiParameter.QUERY)],
        responses=MessageListSerializer,
    ),
    events=extend_schema(tags=["Tickets"]),
    comments=extend_schema(tags=["Tickets"]),
    attachments=extend_schema(tags=["Tickets"]),
    comment_attachments=extend_schema(
        tags=["Tickets"],
        parameters=[OpenApiParameter("comment_id", int, OpenApiParameter.PATH)],
    ),
)

attachment_download_schema = extend_schema_view(
    get=extend_schema(
        tags=["Attachments"],
        parameters=[OpenApiParameter("pk", int, OpenApiParameter.PATH)],
        responses=DownloadLinkSerializer,
    )
)

canned_reply_schema = extend_schema_view(
    list=extend_schema(tags=["Canned replies"]),
    retrieve=extend_schema(tags=["Canned replies"]),
    create=extend_schema(tags=["Canned replies"]),
    partial_update=extend_schema(tags=["Canned replies"]),
    destroy=extend_schema(tags=["Canned replies"]),
)

tag_schema = extend_schema_view(
    list=extend_schema(tags=["Tags"]),
    retrieve=extend_schema(tags=["Tags"]),
    create=extend_schema(tags=["Tags"]),
    partial_update=extend_schema(tags=["Tags"]),
    destroy=extend_schema(tags=["Tags"]),
)
