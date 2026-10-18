from rest_framework import serializers


class ReadMarkSerializer(serializers.Serializer):
    last_read_comment_id = serializers.IntegerField(
        required=False, min_value=1, max_value=2**63 - 1
    )


class ReadStateSerializer(serializers.Serializer):
    last_read_comment_id = serializers.IntegerField(read_only=True)
    unread_count = serializers.IntegerField(read_only=True)
