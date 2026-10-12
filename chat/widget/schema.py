from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view

from chat.widget.serializers import (
    ConversationCreateSerializer,
    WidgetConfigSerializer,
    WidgetConversationStartSerializer,
    WidgetMessageInputSerializer,
    WidgetMessageListSerializer,
    WidgetMessageSerializer,
    WidgetUploadSerializer,
)
from core.serializers import DownloadLinkSerializer

TAGS = ["Widget"]
PK = OpenApiParameter("pk", int, OpenApiParameter.PATH)


class VisitorTokenScheme(OpenApiAuthenticationExtension):
    target_class = "chat.widget.auth.VisitorTokenAuthentication"
    name = "visitorToken"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "X-Visitor-Token"}


widget_config_schema = extend_schema_view(
    get=extend_schema(
        tags=TAGS,
        parameters=[OpenApiParameter("key", str, OpenApiParameter.QUERY, required=True)],
        responses=WidgetConfigSerializer,
    )
)

conversation_create_schema = extend_schema_view(
    post=extend_schema(
        tags=TAGS,
        request=ConversationCreateSerializer,
        responses={200: WidgetConversationStartSerializer, 201: WidgetConversationStartSerializer},
    )
)

message_schema = extend_schema_view(
    get=extend_schema(
        tags=TAGS,
        parameters=[PK, OpenApiParameter("after", int, OpenApiParameter.QUERY)],
        responses=WidgetMessageListSerializer,
    ),
    post=extend_schema(
        tags=TAGS,
        parameters=[PK],
        request=WidgetMessageInputSerializer,
        responses={200: WidgetMessageSerializer, 201: WidgetMessageSerializer},
    ),
)

attachment_upload_schema = extend_schema_view(
    post=extend_schema(
        tags=TAGS,
        parameters=[PK],
        request={"multipart/form-data": WidgetUploadSerializer},
        responses={200: WidgetMessageSerializer, 201: WidgetMessageSerializer},
    )
)

widget_download_schema = extend_schema_view(
    get=extend_schema(tags=TAGS, parameters=[PK], responses=DownloadLinkSerializer)
)
