from django.conf.urls.defaults import include, patterns, url

from tastypie.api import Api
from mkt.api.resources import AppResource, ValidationResource

api = Api(api_name='apps')
api.register(ValidationResource())
api.register(AppResource())


urlpatterns = patterns('',
    url(r'^', include(api.urls)),
)
