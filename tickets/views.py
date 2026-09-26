from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from tickets.models import Ticket
from tickets.permissions import IsCustomerOwnerOrReadOwn
from tickets.serializers import CommentSerializer, TicketEventSerializer, TicketSerializer


class TicketViewSet(viewsets.ModelViewSet):
    serializer_class = TicketSerializer
    permission_classes = [IsCustomerOwnerOrReadOwn]

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.CUSTOMER:
            return Ticket.objects.filter(customer=user)
        return Ticket.objects.all()

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)

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
