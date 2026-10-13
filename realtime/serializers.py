from rest_framework import serializers

from accounts.models import User
from realtime.presence import STATUSES


class SocketTicketSerializer(serializers.Serializer):
    ticket = serializers.CharField(read_only=True)
    expires_in = serializers.IntegerField(read_only=True)


class OnlineAgentSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    role = serializers.ChoiceField(choices=User.Role.choices, read_only=True)
    status = serializers.ChoiceField(choices=STATUSES, read_only=True)
    max_concurrent_chats = serializers.IntegerField(read_only=True)
    open_chats = serializers.IntegerField(read_only=True)
    accepting_chats = serializers.BooleanField(read_only=True)
