from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter

from mkt.api.v1.urls import urlpatterns as v1_urls
from mkt.feed.views import FeedAppViewSet, FeedItemViewSet


feed = SimpleRouter()
feed.register(r'apps', FeedAppViewSet, base_name='feedapp')
feed.register(r'items', FeedItemViewSet, base_name='feeditem')

urlpatterns = patterns('',
    url(r'^feed/', include(feed.urls)),
) + v1_urls
