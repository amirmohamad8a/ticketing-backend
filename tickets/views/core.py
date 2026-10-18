from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import IsAgentOrAdmin
from tickets.assignment import claim_ticket
from tickets.events import STAFF_ONLY_EVENT_FIELDS
from tickets.export import build_export_response
from tickets.filters import TicketFilter
from tickets.models import Ticket
from tickets.pagination import TicketCursorPagination
from tickets.participants import Participant
from tickets.permissions import (
    AdminOnlyDeleteAndRestore,
    CustomerFieldRestrictions,
    IsCustomerOwnerOrReadOwn,
)
from tickets.reads import annotate_unread, mark_conversation_read
from tickets.schema import ticket_schema
from tickets.serializers import (
    CustomerTicketSerializer,
    ReadMarkSerializer,
    ReadStateSerializer,
    TicketEventSerializer,
    TicketSerializer,
)
from tickets.services import delete_ticket, restore_ticket
from tickets.throttles import ExportThrottle
from tickets.views.attachments import AttachmentsMixin
from tickets.views.messages import MessagesMixin
from tickets.views.ratings import RatingsMixin


class CoreActionsMixin:
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
            Participant.from_request(request),
            comment_id=serializer.validated_data.get("last_read_comment_id"),
        )
        return Response(ReadStateSerializer(state).data)

    @action(detail=True, methods=["get"], pagination_class=None)
    def events(self, request, pk=None):
        ticket = self.get_object()
        events = ticket.events.all()
        if request.user.role == User.Role.CUSTOMER:
            events = events.exclude(field_changed__in=STAFF_ONLY_EVENT_FIELDS)
        serializer = TicketEventSerializer(events, many=True)
        return Response(serializer.data)


@ticket_schema
class TicketViewSet(
    CoreActionsMixin, MessagesMixin, AttachmentsMixin, RatingsMixin, viewsets.ModelViewSet
):
    serializer_class = TicketSerializer
    permission_classes = [
        IsCustomerOwnerOrReadOwn,
        CustomerFieldRestrictions,
        AdminOnlyDeleteAndRestore,
    ]
    filter_backends = [DjangoFilterBackend]
    filterset_class = TicketFilter
    pagination_class = TicketCursorPagination
