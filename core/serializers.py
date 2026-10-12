from rest_framework import serializers


class DownloadLinkSerializer(serializers.Serializer):
    url = serializers.URLField(read_only=True)
    expires_in = serializers.IntegerField(read_only=True)
