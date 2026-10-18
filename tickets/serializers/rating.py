from rest_framework import serializers

from tickets.models import TicketRating


class TicketRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketRating
        fields = ["score", "comment", "created_at"]
        read_only_fields = ["created_at"]
