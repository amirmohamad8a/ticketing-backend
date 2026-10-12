from drf_spectacular.utils import extend_schema, extend_schema_view

from chat.serializers import SiteSerializer

site_schema = extend_schema_view(
    list=extend_schema(tags=["Sites"]),
    retrieve=extend_schema(tags=["Sites"]),
    create=extend_schema(tags=["Sites"]),
    partial_update=extend_schema(tags=["Sites"]),
    rotate_key=extend_schema(tags=["Sites"], request=None, responses=SiteSerializer),
)
