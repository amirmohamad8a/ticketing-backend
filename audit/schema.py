from drf_spectacular.utils import extend_schema, extend_schema_view

from audit.serializers import AuditPageSerializer, AuditQuerySerializer

audit_schema = extend_schema_view(
    get=extend_schema(
        tags=["Audit"],
        parameters=[AuditQuerySerializer],
        responses=AuditPageSerializer,
    )
)
