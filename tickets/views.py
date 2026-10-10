from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from tickets.filters import TicketFilter
from tickets.models import Ticket
from tickets.pagination import TicketCursorPagination
from tickets.permissions import (
    AdminOnlyDeleteAndRestore,
    CustomerFieldRestrictions,
    IsCustomerOwnerOrReadOwn,
)
from tickets.schema import ticket_schema
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
            queryset = ticket.comments.all()
            if request.user.role == User.Role.CUSTOMER:
                queryset = queryset.filter(is_internal=False)
            serializer = CommentSerializer(queryset, many=True)
            return Response(serializer.data)

        serializer = CommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_internal = serializer.validated_data.get("is_internal", False)
        if request.user.role == User.Role.CUSTOMER:
            is_internal = False
        comment = serializer.save(ticket=ticket, author=request.user, is_internal=is_internal)
        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"])
    def attachments(self, request, pk=None):
        ticket = self.get_object()

        if request.method == "GET":
            serializer = AttachmentSerializer(ticket.attachments.all(), many=True)
            return Response(serializer.data)

        serializer = AttachmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attachment = serializer.save(ticket=ticket, uploaded_by=request.user)
        return Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)
