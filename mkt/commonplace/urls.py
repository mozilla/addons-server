from django.conf import settings
from django.conf.urls import include, patterns, url

import amo
from . import views
from mkt.ratings.urls import detail_patterns as reviews_detail_patterns


def fireplace_route(path, name=None):
    """
    Helper function for building Fireplace URLs. `path` is the URL route,
    and `name` (if specified) is the name given to the route.
    """
    kwargs = {}
    if name:
        kwargs['name'] = name
    return url('^%s$' % path, views.commonplace, {'repo': 'fireplace'},
               **kwargs)

fireplace_reviews_patterns = patterns('',
    fireplace_route('flag', 'ratings.flag'),
    fireplace_route('delete', 'ratings.delete'),
)

fireplace_app_patterns = patterns('',
    fireplace_route('', 'detail'),
    fireplace_route('abuse', 'detail.abuse'),
    fireplace_route('privacy', 'detail.privacy'),
    fireplace_route('reviews/', 'ratings.list'),
    fireplace_route('reviews/add', 'ratings.add'),
    url('^(?P<review_id>\d+)/', include(fireplace_reviews_patterns)),
    # Load actual Zamboni views. (ratings RSS, helpers for reviewer tools)
    url('^(?P<review_id>\d+)/', include(reviews_detail_patterns)),
)

urlpatterns = patterns('',
    # Fireplace:
    url('^$', views.commonplace, {'repo': 'fireplace'}, name='home'),
    url('^server.html$', views.commonplace, {'repo': 'fireplace'},
        name='commonplace.fireplace'),
    ('^app/%s/' % amo.APP_SLUG, include(fireplace_app_patterns)),

    # Commbadge:
    url('^comm/app/%s$' % amo.APP_SLUG, views.commonplace,
        {'repo': 'commbadge'},
        name='commonplace.commbadge.app_dashboard'),
    url('^comm/thread/(?P<thread_id>\d+)$', views.commonplace,
        {'repo': 'commbadge'},
        name='commonplace.commbadge.show_thread'),
    url('^comm/.*$', views.commonplace, {'repo': 'commbadge'},
        name='commonplace.commbadge'),

    # Rocketfuel:
    url('^curation/.*$', views.commonplace, {'repo': 'rocketfuel'},
        name='commonplace.rocketfuel'),

    # Stats:
    url('^statistics/app/%s$' % amo.APP_SLUG, views.commonplace,
        {'repo': 'marketplace-stats'},
        name='commonplace.stats.app_dashboard'),
    url('^statistics/.*$', views.commonplace, {'repo': 'marketplace-stats'},
        name='commonplace.stats'),

    url('^manifest.appcache$', views.appcache_manifest,
        name='commonplace.appcache'),

)

if settings.DEBUG:
    # More Fireplace stuff, only for local dev:
    urlpatterns += patterns('',
        fireplace_route('category/.*'),
        fireplace_route('collection/.*'),
        fireplace_route('debug'),
        fireplace_route('feedback'),
        fireplace_route('privacy-policy'),
        fireplace_route('purchases'),
        fireplace_route('search/?'),
        fireplace_route('settings'),
        fireplace_route('terms-of-use'),
        fireplace_route('tests'),
    )
