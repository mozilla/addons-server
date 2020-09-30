from django.conf.urls import include
from django.urls import re_path

from rest_framework.routers import SimpleRouter

from olympia.shelves.views import ShelfViewSet

router = SimpleRouter()
router.register('', ShelfViewSet, basename='shelves')

urlpatterns = [
    re_path(r'', include(router.urls)),
]
