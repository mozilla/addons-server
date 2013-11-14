from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter

from mkt.api.v1.urls import urlpatterns as v1_urls
from mkt.feed.views import FeedItemViewSet


feed = SimpleRouter()
feed.register(r'items', FeedItemViewSet, base_name='feed_items')

urlpatterns = patterns('',
    url(r'^feed/', include(feed.urls)),
) + v1_urls
