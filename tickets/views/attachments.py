from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from accounts.models import User
from accounts.permissions import STAFF_ROLES
from tickets.schema import attachments_schema, comment_attachments_schema
from tickets.selectors import visible_attachments
from tickets.serializers import AttachmentSerializer
from tickets.throttles import AttachmentUploadThrottle

UPLOAD_THROTTLES = [UserRateThrottle, AttachmentUploadThrottle]


class AttachmentsMixin:
    def _attachments_response(self, request, queryset, *, allow_internal=False, **parent):
        context = {"request": request}
        if request.method == "GET":
            queryset = visible_attachments(request.user, queryset)
            return Response(AttachmentSerializer(queryset, many=True, context=context).data)

        serializer = AttachmentSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        is_internal = (
            allow_internal
            and request.user.role in STAFF_ROLES
            and serializer.validated_data.get("is_internal", False)
        )
        attachment = serializer.save(uploaded_by=request.user, is_internal=is_internal, **parent)
        return Response(
            AttachmentSerializer(attachment, context=context).data,
            status=status.HTTP_201_CREATED,
        )

    @attachments_schema
    @action(
        detail=True,
        methods=["get", "post"],
        pagination_class=None,
        throttle_classes=UPLOAD_THROTTLES,
    )
    def attachments(self, request, pk=None):
        ticket = self.get_object()
        return self._attachments_response(
            request, ticket.attachments.all(), allow_internal=True, ticket=ticket
        )

    @comment_attachments_schema
    @action(
        detail=True,
        methods=["get", "post"],
        url_path=r"comments/(?P<comment_id>\d+)/attachments",
        url_name="comment-attachments",
        pagination_class=None,
        throttle_classes=UPLOAD_THROTTLES,
    )
    def comment_attachments(self, request, pk=None, comment_id=None):
        ticket = self.get_object()
        comments = ticket.comments.all()
        if request.user.role == User.Role.CUSTOMER:
            comments = comments.filter(is_internal=False)
        comment = get_object_or_404(comments, pk=comment_id)
        if request.method == "POST" and comment.author_id != request.user.id:
            raise PermissionDenied(_("Only the author of a comment can attach files to it."))
        return self._attachments_response(request, comment.attachments.all(), comment=comment)
