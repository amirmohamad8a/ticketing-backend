from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from tickets.models import Ticket
from tickets.permissions import IsCustomerOwnerOrReadOwn
from tickets.serializers import TicketEventSerializer, TicketSerializer


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
