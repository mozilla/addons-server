from django.conf.urls.defaults import include, patterns, url

from tastypie.api import Api
from mkt.api.resources import ValidationResource

validation = Api(api_name='apps')
validation.register(ValidationResource())

urlpatterns = patterns('',
    url(r'^', include(validation.urls)),
)
