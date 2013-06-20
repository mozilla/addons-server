from django.conf.urls import include, patterns, url

from tastypie.api import Api
from mkt.fireplace.api import AppResource

fireplace = Api(api_name='fireplace')
fireplace.register(AppResource())

urlpatterns = patterns('',
    url(r'', include(fireplace.urls)),
)
