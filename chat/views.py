from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from accounts.permissions import IsAdmin
from chat.models import Site
from chat.pagination import SiteCursorPagination
from chat.schema import site_schema
from chat.serializers import SiteSerializer


@site_schema
class SiteViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer
    permission_classes = [IsAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["key", "is_active"]
    pagination_class = SiteCursorPagination
    http_method_names = ["get", "post", "patch", "head", "options"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "site_management"

    @action(detail=True, methods=["post"], url_path="rotate-key", url_name="rotate-key")
    def rotate_key(self, request, pk=None):
        site = self.get_object()
        site.rotate_key()
        return Response(self.get_serializer(site).data)
