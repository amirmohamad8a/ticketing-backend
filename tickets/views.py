from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsAgentOrAdmin
from core.downloads import build_download_link
from tickets.assignment import claim_ticket
from tickets.events import STAFF_ONLY_EVENT_FIELDS
from tickets.export import build_export_response
from tickets.filters import TicketFilter
from tickets.messages import MESSAGES_PAGE_SIZE, message_page, post_customer_message, post_message
from tickets.models import Ticket, TicketRating
from tickets.pagination import TicketCursorPagination
from tickets.permissions import (
    AdminOnlyDeleteAndRestore,
    CustomerFieldRestrictions,
    IsCustomerOwnerOrReadOwn,
)
from tickets.ratings import rate_ticket
from tickets.reads import annotate_unread, mark_conversation_read, visible_comments
from tickets.schema import (
    attachment_download_schema,
    attachments_schema,
    comment_attachments_schema,
    comments_schema,
    rating_schema,
    ticket_schema,
)
from tickets.selectors import visible_attachments
from tickets.serializers import (
    AttachmentSerializer,
    CommentSerializer,
    CustomerTicketSerializer,
    MessageListSerializer,
    MessageQuerySerializer,
    ReadMarkSerializer,
    ReadStateSerializer,
    TicketEventSerializer,
    TicketRatingSerializer,
    TicketSerializer,
)
from tickets.services import delete_ticket, restore_ticket
from tickets.throttles import AttachmentUploadThrottle, ExportThrottle

UPLOAD_THROTTLES = [UserRateThrottle, AttachmentUploadThrottle]


@ticket_schema
class TicketViewSet(viewsets.ModelViewSet):
    serializer_class = TicketSerializer
    permission_classes = [
        IsCustomerOwnerOrReadOwn,
        CustomerFieldRestrictions,
        AdminOnlyDeleteAndRestore,
    ]
    filter_backends = [DjangoFilterBackend]
    filterset_class = TicketFilter
    pagination_class = TicketCursorPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Ticket.objects.none()
        user = self.request.user
        if self.action == "restore":
            queryset = Ticket.all_objects.deleted()
        else:
            queryset = Ticket.objects.all()
        if user.role == User.Role.CUSTOMER:
            queryset = queryset.filter(customer=user)
        else:
            queryset = queryset.select_related("visitor", "site").prefetch_related("tags")
        if self.action == "export":
            return queryset
        return annotate_unread(queryset, user)

    def get_serializer_class(self):
        user = getattr(self.request, "user", None)
        if getattr(user, "role", None) == User.Role.CUSTOMER:
            return CustomerTicketSerializer
        return TicketSerializer

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)

    def perform_destroy(self, instance):
        delete_ticket(instance, self.request.user)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        ticket = self.get_object()
        serializer = self.get_serializer(ticket, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        refreshed = self.get_queryset().get(pk=ticket.pk)
        return Response(self.get_serializer(refreshed).data)

    def _attachments_response(self, request, queryset, **parent):
        context = {"request": request}
        if request.method == "GET":
            queryset = visible_attachments(request.user, queryset)
            return Response(AttachmentSerializer(queryset, many=True, context=context).data)

        serializer = AttachmentSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        attachment = serializer.save(uploaded_by=request.user, **parent)
        return Response(
            AttachmentSerializer(attachment, context=context).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[IsAgentOrAdmin],
        throttle_classes=[ExportThrottle],
    )
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        return build_export_response(queryset)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        ticket = self.get_object()
        restore_ticket(ticket, request.user)
        return Response(self.get_serializer(ticket).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAgentOrAdmin])
    def claim(self, request, pk=None):
        ticket = self.get_object()
        claim_ticket(ticket.pk, request.user, request.user)
        refreshed = self.get_queryset().get(pk=ticket.pk)
        return Response(self.get_serializer(refreshed).data)

    @action(detail=True, methods=["post"], url_path="read", url_name="read")
    def mark_read(self, request, pk=None):
        ticket = self.get_object()
        serializer = ReadMarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        state = mark_conversation_read(
            ticket,
            comment_id=serializer.validated_data.get("last_read_comment_id"),
            user=request.user,
        )
        return Response(ReadStateSerializer(state).data)

    @rating_schema
    @action(detail=True, methods=["get", "post"])
    def rating(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "GET":
            record = get_object_or_404(TicketRating, ticket=ticket)
            return Response(TicketRatingSerializer(record).data)
        if ticket.customer_id != request.user.pk:
            raise PermissionDenied(_("Only the owner of a ticket can rate it."))
        serializer = TicketRatingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = rate_ticket(ticket, **serializer.validated_data)
        return Response(TicketRatingSerializer(record).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None):
        ticket = self.get_object()
        query = MessageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        after = query.validated_data["after"]
        queryset = visible_comments(ticket, user=request.user).select_related("author")
        rows, has_more = message_page(queryset, after, MESSAGES_PAGE_SIZE)
        payload = {
            "results": rows,
            "has_more": has_more,
            "unread_count": ticket.unread_count,
        }
        return Response(MessageListSerializer(payload, context={"request": request}).data)

    @action(detail=True, methods=["get"], pagination_class=None)
    def events(self, request, pk=None):
        ticket = self.get_object()
        events = ticket.events.all()
        if request.user.role == User.Role.CUSTOMER:
            events = events.exclude(field_changed__in=STAFF_ONLY_EVENT_FIELDS)
        serializer = TicketEventSerializer(events, many=True)
        return Response(serializer.data)

    @comments_schema
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def comments(self, request, pk=None):
        ticket = self.get_object()

        if request.method == "GET":
            queryset = ticket.comments.select_related("author")
            if request.user.role == User.Role.CUSTOMER:
                queryset = queryset.filter(is_internal=False)
            latest = list(queryset.order_by("-id")[: MESSAGES_PAGE_SIZE + 1])
            has_more = len(latest) > MESSAGES_PAGE_SIZE
            rows = sorted(latest[:MESSAGES_PAGE_SIZE], key=lambda comment: comment.id)
            response = Response(CommentSerializer(rows, many=True).data)
            if has_more:
                response["X-Results-Truncated"] = "true"
            return response

        serializer = CommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        is_internal = data.get("is_internal", False)
        is_customer = request.user.role == User.Role.CUSTOMER
        if is_customer:
            comment, created = post_customer_message(
                ticket,
                data["body"],
                actor=request.user,
                is_internal=False,
                client_msg_id=data.get("client_msg_id"),
            )
        else:
            comment, created = post_message(
                ticket,
                data["body"],
                author=request.user,
                is_internal=is_internal,
                client_msg_id=data.get("client_msg_id"),
            )
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(CommentSerializer(comment).data, status=status_code)

    @attachments_schema
    @action(
        detail=True,
        methods=["get", "post"],
        pagination_class=None,
        throttle_classes=UPLOAD_THROTTLES,
    )
    def attachments(self, request, pk=None):
        ticket = self.get_object()
        return self._attachments_response(request, ticket.attachments.all(), ticket=ticket)

    @comment_attachments_schema
    @action(
        detail=True,
        methods=["get", "post"],
        url_path=r"comments/(?P<comment_id>\d+)/attachments",
        url_name="comment-attachments",
        pagination_class=None,
        throttle_classes=UPLOAD_THROTTLES,
    )
    def comment_attachments(self, request, pk=None, comment_id=None):
        ticket = self.get_object()
        comments = ticket.comments.all()
        if request.user.role == User.Role.CUSTOMER:
            comments = comments.filter(is_internal=False)
        comment = get_object_or_404(comments, pk=comment_id)
        if request.method == "POST" and comment.author_id != request.user.id:
            raise PermissionDenied(_("Only the author of a comment can attach files to it."))
        return self._attachments_response(request, comment.attachments.all(), comment=comment)


@attachment_download_schema
class AttachmentDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        attachment = get_object_or_404(visible_attachments(request.user), pk=pk)
        link = build_download_link(
            request, attachment.file, attachment.content_type, attachment.original_name
        )
        return Response(link)
