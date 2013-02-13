from django.conf.urls import include, patterns, url

from tastypie.api import Api
from .resources import MonolithData

api = Api(api_name='monolith')
api.register(MonolithData())

urlpatterns = patterns('',
    url(r'^', include(api.urls)),
)
