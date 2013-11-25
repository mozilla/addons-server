from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter
from tastypie.api import Api

from mkt.fireplace.api import AppViewSet
from mkt.search.api import WithFeaturedResource

fireplace = Api(api_name='fireplace')
fireplace.register(WithFeaturedResource())
apps = SimpleRouter()
apps.register(r'app', AppViewSet, base_name='fireplace-app')

urlpatterns = patterns('',
    url(r'', include(fireplace.urls)),
    url(r'^fireplace/', include(apps.urls)),
)
