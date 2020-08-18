from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from olympia.shelves import views

router = SimpleRouter()
router.register('info', views.ShelfViewSet, basename='shelves-info')

urlpatterns = [
    url(r'', include(router.urls)),
    url(r'', views.HomepageView.as_view(), name='shelves'),
]
