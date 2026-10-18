from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from tickets.models import Ticket

DEFAULT_RANGE_DAYS = 30
MAX_RANGE_DAYS = 366


class StatsQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    def validate(self, attrs):
        date_to = attrs.get("date_to") or timezone.localdate()
        date_from = attrs.get("date_from") or date_to - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        if date_from > date_to:
            raise serializers.ValidationError(
                {"date_from": _("The start date must not be after the end date.")}
            )
        if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
            message = _("The date range can span at most %(max)s days.")
            raise serializers.ValidationError({"date_to": message % {"max": MAX_RANGE_DAYS}})
        return {"date_from": date_from, "date_to": date_to}


class StatsRangeSerializer(serializers.Serializer):
    date_from = serializers.DateField(read_only=True)
    date_to = serializers.DateField(read_only=True)


class AgentLoadSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    open_chats = serializers.IntegerField(read_only=True)


class DailyCountSerializer(serializers.Serializer):
    date = serializers.DateField(read_only=True)
    count = serializers.IntegerField(read_only=True)


class ChannelCountSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=Ticket.Channel.choices, read_only=True)
    count = serializers.IntegerField(read_only=True)


class StatsSerializer(serializers.Serializer):
    range = StatsRangeSerializer(read_only=True)
    queue_size = serializers.IntegerField(read_only=True)
    open_chats_per_agent = AgentLoadSerializer(many=True, read_only=True)
    average_first_response_seconds = serializers.FloatField(read_only=True, allow_null=True)
    average_resolution_seconds = serializers.FloatField(read_only=True, allow_null=True)
    average_rating = serializers.FloatField(read_only=True, allow_null=True)
    ratings_total = serializers.IntegerField(read_only=True)
    tickets_total = serializers.IntegerField(read_only=True)
    tickets_per_day = DailyCountSerializer(many=True, read_only=True)
    tickets_per_channel = ChannelCountSerializer(many=True, read_only=True)
