from django.urls import reverse

from rest_framework import serializers

from core.uploads import ATTACHMENT_UPLOAD_POLICY, clean_file_name
from tickets.models import Attachment


class AttachmentSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            "id",
            "ticket",
            "comment",
            "file",
            "original_name",
            "download_url",
            "uploaded_by",
            "size",
            "content_type",
            "is_internal",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "ticket",
            "comment",
            "original_name",
            "uploaded_by",
            "size",
            "content_type",
            "created_at",
        ]
        extra_kwargs = {"file": {"write_only": True}}

    def get_download_url(self, obj) -> str:
        path = reverse("attachment-download", args=[obj.pk])
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path

    def validate_file(self, value):
        return ATTACHMENT_UPLOAD_POLICY.validate(value, max_size_bytes=Attachment.MAX_SIZE_BYTES)

    def create(self, validated_data):
        file_obj = validated_data["file"]
        validated_data["size"] = file_obj.size
        validated_data["content_type"] = getattr(file_obj, "content_type", "") or ""
        validated_data["original_name"] = clean_file_name(file_obj.name)
        return super().create(validated_data)
