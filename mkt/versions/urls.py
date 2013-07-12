from rest_framework import routers

from .api import VersionViewSet

router = routers.DefaultRouter()
router.register(r'versions', VersionViewSet)
urlpatterns = router.urls
