from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from chat.widget.serializers import (
    ConversationCreateSerializer,
    WidgetConfigSerializer,
    WidgetContactInputSerializer,
    WidgetContactSerializer,
    WidgetConversationStartSerializer,
    WidgetMessageInputSerializer,
    WidgetMessageListSerializer,
    WidgetMessageSerializer,
    WidgetUploadSerializer,
)
from core.serializers import DownloadLinkSerializer
from realtime.serializers import SocketTicketSerializer
from tickets.serializers import ReadMarkSerializer, ReadStateSerializer, TicketRatingSerializer

TAGS = ["Widget"]
ID = OpenApiParameter("id", int, OpenApiParameter.PATH)

CONVERSATION_CLOSED = OpenApiResponse(
    description="The conversation is resolved or closed (`conversation_closed`)."
)
RATING_CONFLICT = OpenApiResponse(
    description=(
        "The conversation is not resolved yet or was already rated "
        "(`ticket_not_resolved`, `ticket_already_rated`)."
    )
)


class VisitorTokenScheme(OpenApiAuthenticationExtension):
    target_class = "chat.widget.auth.VisitorTokenAuthentication"
    name = "visitorToken"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "X-Visitor-Token"}


widget_config_schema = extend_schema_view(
    get=extend_schema(
        tags=TAGS,
        parameters=[OpenApiParameter("key", str, OpenApiParameter.QUERY, required=True)],
        responses={
            200: WidgetConfigSerializer,
            403: OpenApiResponse(description="The request origin is not allowed for the site."),
            404: OpenApiResponse(description="No active site has this key."),
        },
    )
)

conversation_create_schema = extend_schema_view(
    post=extend_schema(
        tags=TAGS,
        request=ConversationCreateSerializer,
        responses={
            200: WidgetConversationStartSerializer,
            201: WidgetConversationStartSerializer,
            404: OpenApiResponse(description="No active site has this key."),
        },
    )
)

message_schema = extend_schema_view(
    get=extend_schema(
        tags=TAGS,
        parameters=[ID, OpenApiParameter("after", int, OpenApiParameter.QUERY)],
        responses=WidgetMessageListSerializer,
    ),
    post=extend_schema(
        tags=TAGS,
        parameters=[ID],
        request=WidgetMessageInputSerializer,
        responses={
            200: WidgetMessageSerializer,
            201: WidgetMessageSerializer,
            409: CONVERSATION_CLOSED,
        },
    ),
)

conversation_read_schema = extend_schema_view(
    post=extend_schema(
        tags=TAGS,
        parameters=[ID],
        request=ReadMarkSerializer,
        responses=ReadStateSerializer,
    )
)

conversation_contact_schema = extend_schema_view(
    post=extend_schema(
        tags=TAGS,
        parameters=[ID],
        request=WidgetContactInputSerializer,
        responses={200: WidgetContactSerializer, 409: CONVERSATION_CLOSED},
    )
)

conversation_rating_schema = extend_schema_view(
    get=extend_schema(tags=TAGS, parameters=[ID], responses=TicketRatingSerializer),
    post=extend_schema(
        tags=TAGS,
        parameters=[ID],
        request=TicketRatingSerializer,
        responses={201: TicketRatingSerializer, 409: RATING_CONFLICT},
    ),
)

attachment_upload_schema = extend_schema_view(
    post=extend_schema(
        tags=TAGS,
        parameters=[ID],
        request={"multipart/form-data": WidgetUploadSerializer},
        responses={
            200: WidgetMessageSerializer,
            201: WidgetMessageSerializer,
            409: CONVERSATION_CLOSED,
        },
    )
)

widget_download_schema = extend_schema_view(
    get=extend_schema(tags=TAGS, parameters=[ID], responses=DownloadLinkSerializer)
)

widget_socket_ticket_schema = extend_schema_view(
    post=extend_schema(tags=TAGS, request=None, responses=SocketTicketSerializer)
)
