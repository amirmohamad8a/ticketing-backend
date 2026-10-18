from rest_framework import viewsets

from accounts.permissions import IsAgentOrAdmin
from tickets.models import CannedReply
from tickets.schema import canned_reply_schema
from tickets.serializers.canned import CannedReplySerializer


@canned_reply_schema
class CannedReplyViewSet(viewsets.ModelViewSet):
    queryset = CannedReply.objects.all()
    serializer_class = CannedReplySerializer
    permission_classes = [IsAgentOrAdmin]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
