from django.conf.urls import include, patterns, url

from tastypie.api import Api
from mkt.fireplace.api import AppResource

from mkt.ratings.resources import FireplaceRatingResource
from mkt.search.api import WithFeaturedResource

fireplace = Api(api_name='fireplace')
fireplace.register(WithFeaturedResource())
fireplace.register(AppResource())
fireplace.register(FireplaceRatingResource())

urlpatterns = patterns('',
    url(r'', include(fireplace.urls)),
)
