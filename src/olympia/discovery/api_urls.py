from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from . import views

# Because we're registering things at "/discovery/" we don't want the trailing
# slash that comes with the Router by default.
discovery = SimpleRouter(trailing_slash=False)
discovery.register(r'', views.DiscoveryViewSet, base_name='discovery')

urlpatterns = [
    url(r'', include(discovery.urls)),
]
