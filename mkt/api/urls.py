"""
API URL versioning goes here.

The "current" version should be marked via the empty pattern. Each other
version's URLs should be loaded in this way, with the most recent versions
first:

    url('^v2/', include('mkt.api.v2.urls')),
    url('^v1/', include('mkt.api.v1.urls')),

Each version's URLs should live in its own submodule, and should inherit from
the previous version's patterns. Example:

    from mkt.api.v1.urls import urlpatterns as v1_urls

    router = SimpleRouter()
    router.register(r'widgets', WidgetViewSet, base_name='widget')

    urlpatterns = patterns('',
        url(r'^widgets/', include(feed.urls)),
    ) + v1_urls

Strategies for deprecating and removing endpoints are currently being discussed
in bug 942934.
"""

from django.conf.urls import include, patterns, url


urlpatterns = patterns('',
    url('^v2/', include('mkt.api.v2.urls')),
    url('^v1/', include('mkt.api.v1.urls')),

    # Necessary for backwards-compatibility. We assume that this always means
    # API version 1. The namespace ensures that no URLS are ever reversed to
    # this pattern. Yummycake because we already ate the tastypie.
    url('', include('mkt.api.v1.urls', namespace='yummycake')),
)
