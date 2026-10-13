from rest_framework.response import Response
from rest_framework.views import APIView

from stats.queries import build_stats
from stats.schema import stats_schema
from stats.serializers import StatsQuerySerializer, StatsSerializer
from tickets.permissions import IsAgentOrAdmin


@stats_schema
class StatsView(APIView):
    permission_classes = [IsAgentOrAdmin]

    def get(self, request):
        query = StatsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        stats = build_stats(**query.validated_data)
        return Response(StatsSerializer(stats).data)
