from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from olympia.shelves import views

router = SimpleRouter()
router.register('', views.ShelfViewSet, basename='shelves')

urlpatterns = [
    url(r'', include(router.urls)),
]
