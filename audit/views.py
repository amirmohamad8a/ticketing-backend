from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param
from rest_framework.views import APIView

from accounts.permissions import IsAdmin
from audit.queries import audit_page
from audit.schema import audit_schema
from audit.serializers import AuditPageSerializer, AuditQuerySerializer


@audit_schema
class AuditLogView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        query = AuditQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = dict(query.validated_data)
        cursor = filters.pop("cursor", None)
        rows, next_cursor = audit_page(filters, cursor)
        next_url = None
        if next_cursor is not None:
            next_url = replace_query_param(request.build_absolute_uri(), "cursor", next_cursor)
        return Response(AuditPageSerializer({"next": next_url, "results": rows}).data)
