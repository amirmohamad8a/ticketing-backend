from rest_framework.throttling import UserRateThrottle


class ExportThrottle(UserRateThrottle):
    scope = "export"


class AttachmentUploadThrottle(UserRateThrottle):
    scope = "attachment_upload"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)
