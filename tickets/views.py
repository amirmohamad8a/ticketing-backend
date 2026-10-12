from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from core.downloads import build_download_link
from tickets.filters import TicketFilter
from tickets.messages import post_message
from tickets.models import Attachment, Ticket
from tickets.pagination import TicketCursorPagination
from tickets.permissions import (
    AdminOnlyDeleteAndRestore,
    CustomerFieldRestrictions,
    IsCustomerOwnerOrReadOwn,
)
from tickets.schema import attachment_download_schema, ticket_schema
from tickets.serializers import (
    AttachmentSerializer,
    CommentSerializer,
    CustomerTicketSerializer,
    TicketEventSerializer,
    TicketSerializer,
)


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
            return queryset.filter(customer=user)
        return queryset

    def get_serializer_class(self):
        user = getattr(self.request, "user", None)
        if getattr(user, "role", None) == User.Role.CUSTOMER:
            return CustomerTicketSerializer
        return TicketSerializer

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)

    def _attachments_response(self, request, queryset, **parent):
        context = {"request": request}
        if request.method == "GET":
            return Response(AttachmentSerializer(queryset, many=True, context=context).data)

        serializer = AttachmentSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        attachment = serializer.save(uploaded_by=request.user, **parent)
        return Response(
            AttachmentSerializer(attachment, context=context).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        ticket = self.get_object()
        ticket.restore()
        return Response(self.get_serializer(ticket).data)

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        ticket = self.get_object()
        serializer = TicketEventSerializer(ticket.events.all(), many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post"])
    def comments(self, request, pk=None):
        ticket = self.get_object()

        if request.method == "GET":
            queryset = ticket.comments.select_related("author")
            if request.user.role == User.Role.CUSTOMER:
                queryset = queryset.filter(is_internal=False)
            serializer = CommentSerializer(queryset, many=True)
            return Response(serializer.data)

        serializer = CommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        is_internal = data.get("is_internal", False)
        if request.user.role == User.Role.CUSTOMER:
            is_internal = False
        comment, created = post_message(
            ticket,
            data["body"],
            author=request.user,
            is_internal=is_internal,
            client_msg_id=data.get("client_msg_id"),
        )
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(CommentSerializer(comment).data, status=status_code)

    @action(detail=True, methods=["get", "post"])
    def attachments(self, request, pk=None):
        ticket = self.get_object()
        return self._attachments_response(request, ticket.attachments.all(), ticket=ticket)

    @action(
        detail=True,
        methods=["get", "post"],
        url_path=r"comments/(?P<comment_id>\d+)/attachments",
        url_name="comment-attachments",
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
        attachment = get_object_or_404(self._visible_attachments(request.user), pk=pk)
        link = build_download_link(
            request, attachment.file, attachment.content_type, attachment.original_name
        )
        return Response(link)

    @staticmethod
    def _visible_attachments(user):
        ticket_scope = Q(ticket__is_deleted=False)
        comment_scope = Q(comment__ticket__is_deleted=False)
        if user.role == User.Role.CUSTOMER:
            ticket_scope &= Q(ticket__customer=user)
            comment_scope &= Q(comment__ticket__customer=user, comment__is_internal=False)
        return Attachment.objects.filter(ticket_scope | comment_scope)
