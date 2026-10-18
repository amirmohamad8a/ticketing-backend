from rest_framework.routers import SimpleRouter

from chat.views import SiteViewSet

router = SimpleRouter()
router.register("sites", SiteViewSet, basename="site")

urlpatterns = router.urls
