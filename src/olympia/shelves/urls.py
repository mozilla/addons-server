from django.urls import include, re_path

from rest_framework.routers import SimpleRouter

from olympia.shelves import views


router = SimpleRouter()
router.register('', views.ShelfViewSet, basename='shelves')
router.register('sponsored', views.SponsoredShelfViewSet, basename='sponsored-shelf')

urlpatterns = [
    re_path(r'', include(router.urls)),
]
