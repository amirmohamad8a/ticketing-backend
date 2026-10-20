from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

from core.serializers import DownloadLinkSerializer
from tickets.exceptions import TicketAlreadyAssigned, TicketAlreadyRated, TicketNotResolved
from tickets.serializers import (
    AttachmentSerializer,
    CommentSerializer,
    MessageListSerializer,
    ReadMarkSerializer,
    ReadStateSerializer,
    TicketEventSerializer,
    TicketRatingSerializer,
    TicketSerializer,
)

TAGS = ["Tickets"]
COMMENT_ID = OpenApiParameter("comment_id", int, OpenApiParameter.PATH)
MULTIPART_ATTACHMENT = {"multipart/form-data": AttachmentSerializer}


def _describe_codes(*exceptions):
    return ", ".join(f"`{exception.default_code}`" for exception in exceptions)


ALREADY_ASSIGNED = OpenApiResponse(
    description=(
        f"The ticket is assigned to someone else ({_describe_codes(TicketAlreadyAssigned)})."
    )
)
RATING_CONFLICT = OpenApiResponse(
    description=(
        "The ticket is not resolved yet or was already rated "
        f"({_describe_codes(TicketNotResolved, TicketAlreadyRated)})."
    )
)


def _stack(*decorators):
    def apply(func):
        for decorator in reversed(decorators):
            func = decorator(func)
        return func

    return apply


ticket_schema = extend_schema_view(
    list=extend_schema(tags=TAGS),
    retrieve=extend_schema(tags=TAGS),
    create=extend_schema(tags=TAGS),
    update=extend_schema(tags=TAGS),
    partial_update=extend_schema(tags=TAGS),
    destroy=extend_schema(tags=TAGS),
    export=extend_schema(
        tags=TAGS,
        filters=True,
        description=(
            "Streams every ticket that matches the current filters as a UTF-8 CSV file "
            "with a byte order mark, so Excel reads Persian text correctly. "
            "Agents and admins only."
        ),
        responses={(200, "text/csv"): OpenApiTypes.STR},
    ),
    restore=extend_schema(tags=TAGS, request=None, responses=TicketSerializer),
    claim=extend_schema(
        tags=TAGS,
        request=None,
        responses={200: TicketSerializer, 409: ALREADY_ASSIGNED},
    ),
    mark_read=extend_schema(
        tags=TAGS,
        request=ReadMarkSerializer,
        responses=ReadStateSerializer,
    ),
    messages=extend_schema(
        tags=TAGS,
        parameters=[OpenApiParameter("after", int, OpenApiParameter.QUERY)],
        responses=MessageListSerializer,
    ),
    events=extend_schema(
        tags=TAGS,
        filters=False,
        responses=TicketEventSerializer(many=True),
    ),
)

rating_schema = _stack(
    extend_schema(
        methods=["GET"],
        tags=TAGS,
        responses=TicketRatingSerializer,
    ),
    extend_schema(
        methods=["POST"],
        tags=TAGS,
        request=TicketRatingSerializer,
        responses={201: TicketRatingSerializer, 409: RATING_CONFLICT},
    ),
)

comments_schema = _stack(
    extend_schema(
        methods=["GET"],
        tags=TAGS,
        deprecated=True,
        filters=False,
        description=(
            "Deprecated: use `GET /api/tickets/{id}/messages/` instead. This endpoint is "
            "capped at the newest messages and does not expose a cursor."
        ),
        responses=CommentSerializer(many=True),
    ),
    extend_schema(
        methods=["POST"],
        tags=TAGS,
        request=CommentSerializer,
        responses={200: CommentSerializer, 201: CommentSerializer},
    ),
)

attachments_schema = _stack(
    extend_schema(
        methods=["GET"],
        tags=TAGS,
        filters=False,
        responses=AttachmentSerializer(many=True),
    ),
    extend_schema(
        methods=["POST"],
        tags=TAGS,
        description=(
            "Agents and admins can set `is_internal` to keep the file hidden from the "
            "customer. The flag is ignored for customers."
        ),
        request=MULTIPART_ATTACHMENT,
        responses={201: AttachmentSerializer},
    ),
)

comment_attachments_schema = _stack(
    extend_schema(
        methods=["GET"],
        tags=TAGS,
        parameters=[COMMENT_ID],
        filters=False,
        responses=AttachmentSerializer(many=True),
    ),
    extend_schema(
        methods=["POST"],
        tags=TAGS,
        parameters=[COMMENT_ID],
        request=MULTIPART_ATTACHMENT,
        responses={201: AttachmentSerializer},
    ),
)

attachment_download_schema = extend_schema_view(
    get=extend_schema(
        tags=["Attachments"],
        parameters=[OpenApiParameter("id", int, OpenApiParameter.PATH)],
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
