from django.conf import settings
from django.conf.urls.defaults import patterns, url, include

from lib.urls_base import handler404, handler500, urlpatterns as base_urls
from mkt.developers.views import login


# These URLs take precedence over existing ones.
urlpatterns = patterns('',
    # Replace the "old" Developer Hub with the "new" Marketplace one.
    ('^developers/', include('mkt.developers.urls')),

    # The new hotness.
    ('^hub/', include('mkt.hub.urls')),
)


# Add our old patterns.
urlpatterns += base_urls


# Override old patterns.
urlpatterns += patterns('',
    # Developer Registration Login.
    url('^login$', login, name='users.login'),
)


# Marketplace UI Experiments.
if getattr(settings, 'POTCH_MARKETPLACE_EXPERIMENTS', False):
    urlpatterns += patterns('',
        ('^marketplace-experiments/', include('mkt.experiments.urls'))
    )
