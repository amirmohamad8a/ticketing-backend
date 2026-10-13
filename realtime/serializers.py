from rest_framework import serializers


class SocketTicketSerializer(serializers.Serializer):
    ticket = serializers.CharField(read_only=True)
    expires_in = serializers.IntegerField(read_only=True)
