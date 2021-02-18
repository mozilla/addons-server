from django.urls import include, re_path

from rest_framework.routers import SimpleRouter

from olympia.shelves import views


router = SimpleRouter()
router.register('', views.ShelfViewSet, basename='shelves')
router.register('editorial', views.EditorialShelfViewSet, basename='shelves-editorial')

urlpatterns = [
    re_path(r'', include(router.urls)),
]
