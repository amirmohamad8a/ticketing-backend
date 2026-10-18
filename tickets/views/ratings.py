from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from tickets.models import TicketRating
from tickets.ratings import rate_ticket
from tickets.schema import rating_schema
from tickets.serializers import TicketRatingSerializer


class RatingsMixin:
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
