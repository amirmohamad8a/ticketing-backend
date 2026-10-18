from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.availability import agents_available
from chat.contact import save_contact
from chat.conversations import conversations_of
from chat.exceptions import ConversationClosed
from chat.models import Visitor
from chat.widget.admission import continue_conversation
from chat.widget.admission import find_site as _find_site
from chat.widget.admission import start_new_conversation
from chat.widget.auth import (
    IsVisitorFromAllowedOrigin,
    VisitorTokenAuthentication,
    ensure_origin_allowed,
)
from chat.widget.pow import issue_challenge
from chat.widget.schema import (
    attachment_upload_schema,
    conversation_contact_schema,
    conversation_create_schema,
    conversation_rating_schema,
    conversation_read_schema,
    message_schema,
    widget_challenge_schema,
    widget_config_schema,
    widget_download_schema,
    widget_socket_ticket_schema,
)
from chat.widget.serializers import (
    ConversationCreateSerializer,
    WidgetAttachmentSerializer,
    WidgetChallengeSerializer,
    WidgetConfigSerializer,
    WidgetContactInputSerializer,
    WidgetContactSerializer,
    WidgetConversationStartSerializer,
    WidgetMessageInputSerializer,
    WidgetMessageListSerializer,
    WidgetMessageQuerySerializer,
    WidgetMessageSerializer,
    WidgetUploadSerializer,
)
from chat.widget.throttles import (
    WidgetIPThrottle,
    WidgetStartThrottle,
    WidgetUploadThrottle,
    WidgetVisitorThrottle,
)
from core.downloads import build_download_link
from realtime.tickets import issue_ticket
from tickets.messages import MESSAGES_PAGE_SIZE, message_page, post_customer_message
from tickets.models import Attachment, Ticket, TicketRating
from tickets.ratings import rate_ticket
from tickets.reads import mark_conversation_read, unread_count, visible_comments
from tickets.serializers import ReadMarkSerializer, ReadStateSerializer, TicketRatingSerializer


def _get_conversation(visitor, pk):
    return get_object_or_404(conversations_of(visitor), pk=pk)


def _ensure_open(ticket):
    if ticket.status in Ticket.FINISHED_STATUSES:
        raise ConversationClosed


class WidgetAPIView(APIView):
    authentication_classes = [VisitorTokenAuthentication]
    permission_classes = [IsVisitorFromAllowedOrigin]
    throttle_classes = [WidgetIPThrottle, WidgetVisitorThrottle]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response


@widget_config_schema
class WidgetConfigView(WidgetAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        site = _find_site(request.query_params.get("key"), "key")
        ensure_origin_allowed(request, site)
        return Response(WidgetConfigSerializer(site).data)


@widget_challenge_schema
class WidgetChallengeView(WidgetAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        site = _find_site(request.query_params.get("key"), "key")
        ensure_origin_allowed(request, site)
        return Response(WidgetChallengeSerializer(issue_challenge(site)).data)


@conversation_create_schema
class ConversationCreateView(WidgetAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [WidgetIPThrottle, WidgetVisitorThrottle, WidgetStartThrottle]

    def post(self, request):
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        visitor = request.auth if isinstance(request.auth, Visitor) else None
        if visitor is not None:
            _visitor, token, ticket, comment, created = continue_conversation(
                visitor, data, request
            )
        else:
            _visitor, token, ticket, comment, created = start_new_conversation(request, data)

        payload = {
            "token": token,
            "conversation": ticket,
            "message": comment,
            "agents_available": agents_available(),
        }
        body = WidgetConversationStartSerializer(payload, context={"request": request}).data
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@message_schema
class MessageListCreateView(WidgetAPIView):
    def get(self, request, pk):
        visitor = request.auth
        ticket = _get_conversation(visitor, pk)
        query = WidgetMessageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        after = query.validated_data["after"]
        queryset = (
            visible_comments(ticket, visitor=visitor)
            .select_related("author", "visitor")
            .prefetch_related("attachments")
        )
        rows, has_more = message_page(queryset, after, MESSAGES_PAGE_SIZE)
        payload = {
            "results": rows,
            "has_more": has_more,
            "agents_available": agents_available(),
            "unread_count": unread_count(ticket, visitor=visitor),
        }
        return Response(WidgetMessageListSerializer(payload, context={"request": request}).data)

    def post(self, request, pk):
        visitor = request.auth
        ticket = _get_conversation(visitor, pk)
        serializer = WidgetMessageInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _ensure_open(ticket)
        data = serializer.validated_data
        comment, created = post_customer_message(
            ticket,
            data["body"],
            visitor=visitor,
            client_msg_id=data.get("client_msg_id") or None,
        )
        body = WidgetMessageSerializer(comment, context={"request": request}).data
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@conversation_read_schema
class ConversationReadView(WidgetAPIView):
    def post(self, request, pk):
        visitor = request.auth
        ticket = _get_conversation(visitor, pk)
        serializer = ReadMarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        state = mark_conversation_read(
            ticket,
            comment_id=serializer.validated_data.get("last_read_comment_id"),
            visitor=visitor,
        )
        return Response(ReadStateSerializer(state).data)


@conversation_contact_schema
class ConversationContactView(WidgetAPIView):
    def post(self, request, pk):
        ticket = _get_conversation(request.auth, pk)
        serializer = WidgetContactInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _ensure_open(ticket)
        data = serializer.validated_data
        visitor = save_contact(
            ticket,
            phone=data.get("phone") or "",
            email=data.get("email") or "",
        )
        return Response(WidgetContactSerializer(visitor).data)


@conversation_rating_schema
class ConversationRatingView(WidgetAPIView):
    def get(self, request, pk):
        ticket = _get_conversation(request.auth, pk)
        record = get_object_or_404(TicketRating, ticket=ticket)
        return Response(TicketRatingSerializer(record).data)

    def post(self, request, pk):
        ticket = _get_conversation(request.auth, pk)
        serializer = TicketRatingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = rate_ticket(ticket, **serializer.validated_data)
        return Response(TicketRatingSerializer(record).data, status=status.HTTP_201_CREATED)


@attachment_upload_schema
class AttachmentCreateView(WidgetAPIView):
    parser_classes = [MultiPartParser]
    throttle_classes = [WidgetIPThrottle, WidgetVisitorThrottle, WidgetUploadThrottle]

    def post(self, request, pk):
        visitor = request.auth
        ticket = _get_conversation(visitor, pk)
        context = {"request": request}
        upload = WidgetUploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        data = upload.validated_data
        file_serializer = WidgetAttachmentSerializer(data={"file": data["file"]}, context=context)
        file_serializer.is_valid(raise_exception=True)
        _ensure_open(ticket)
        comment, created = post_customer_message(
            ticket,
            data["body"],
            visitor=visitor,
            client_msg_id=data.get("client_msg_id") or None,
            on_created=lambda message: file_serializer.save(comment=message),
        )
        body = WidgetMessageSerializer(comment, context=context).data
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@widget_download_schema
class WidgetAttachmentDownloadView(WidgetAPIView):
    def get(self, request, pk):
        attachment = get_object_or_404(self._visible_attachments(request.auth), pk=pk)
        link = build_download_link(
            request, attachment.file, attachment.content_type, attachment.original_name
        )
        return Response(link)

    @staticmethod
    def _visible_attachments(visitor):
        return Attachment.objects.filter(
            comment__ticket__visitor=visitor,
            comment__ticket__is_deleted=False,
            comment__is_internal=False,
        )


@widget_socket_ticket_schema
class WidgetSocketTicketView(WidgetAPIView):
    def post(self, request):
        return Response(issue_ticket(visitor=request.auth))
