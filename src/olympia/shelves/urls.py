from django.urls import include, re_path

from rest_framework.routers import SimpleRouter

from olympia.shelves import views


router = SimpleRouter()
router.register('', views.ShelfViewSet, basename='shelves')

urlpatterns = [
    re_path(r'', include(router.urls)),
]
