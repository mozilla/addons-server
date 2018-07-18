from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from . import views


discovery = SimpleRouter()
discovery.register('discovery', views.DiscoveryViewSet, base_name='discovery')
discovery.register(
    'discovery/editorial',
    views.DiscoveryItemViewSet,
    base_name='discovery-editorial',
)

urlpatterns = [url(r'', include(discovery.urls))]
