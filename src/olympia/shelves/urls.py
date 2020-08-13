from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from olympia.shelves.views import ShelfViewSet

router = SimpleRouter()
router.register('', ShelfViewSet, basename='shelves')

urlpatterns = [
    url(r'', include(router.urls)),
]
