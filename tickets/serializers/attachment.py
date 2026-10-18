from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from rest_framework import serializers

from core.uploads import clean_file_name, ensure_content_matches
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
        if value.size > Attachment.MAX_SIZE_BYTES:
            max_mb = Attachment.MAX_SIZE_BYTES // (1024 * 1024)
            message = _("File too large. Max size is %(max_mb)sMB.")
            raise serializers.ValidationError(message % {"max_mb": max_mb})
        content_type = getattr(value, "content_type", "") or ""
        if content_type not in Attachment.ALLOWED_CONTENT_TYPES:
            message = _("File type '%(content_type)s' is not allowed.")
            raise serializers.ValidationError(message % {"content_type": content_type})
        ensure_content_matches(value, content_type)
        return value

    def create(self, validated_data):
        file_obj = validated_data["file"]
        validated_data["size"] = file_obj.size
        validated_data["content_type"] = getattr(file_obj, "content_type", "") or ""
        validated_data["original_name"] = clean_file_name(file_obj.name)
        return super().create(validated_data)
