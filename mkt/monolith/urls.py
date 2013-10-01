from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter

from .resources import MonolithViewSet


api = SimpleRouter()
api.register('data', MonolithViewSet, base_name='monolith')


urlpatterns = patterns('',
    url(r'^monolith/', include(api.urls)),
)
