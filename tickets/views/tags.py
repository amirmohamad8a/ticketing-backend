from rest_framework import viewsets

from tickets.models import Tag
from tickets.permissions import IsAdminOrAgentReadOnly
from tickets.schema import tag_schema
from tickets.serializers.tags import TagSerializer


@tag_schema
class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [IsAdminOrAgentReadOnly]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        from tickets.services import delete_tag

        delete_tag(instance, self.request.user)
