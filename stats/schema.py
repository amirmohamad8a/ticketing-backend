from drf_spectacular.utils import extend_schema, extend_schema_view

from stats.serializers import StatsQuerySerializer, StatsSerializer

stats_schema = extend_schema_view(
    get=extend_schema(
        tags=["Stats"],
        parameters=[StatsQuerySerializer],
        responses=StatsSerializer,
    )
)
