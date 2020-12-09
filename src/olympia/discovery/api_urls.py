from django.urls import include, re_path

from rest_framework.routers import SimpleRouter

from . import views


discovery = SimpleRouter()
discovery.register('discovery', views.DiscoveryViewSet, basename='discovery')
discovery.register(
    'discovery/editorial', views.DiscoveryItemViewSet, basename='discovery-editorial'
)

urlpatterns = [
    re_path(r'', include(discovery.urls)),
]
