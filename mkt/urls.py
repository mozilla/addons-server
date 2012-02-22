from django.conf import settings
from django.conf.urls.defaults import patterns, url, include

from lib.urls_base import urlpatterns as base_urls
from mkt.developers.views import login

handler404 = 'mkt.site.views.handler404'
handler500 = 'mkt.site.views.handler500'


# These URLs take precedence over existing ones.
urlpatterns = patterns('',
    # Replace the "old" Developer Hub with the "new" Marketplace one.
    ('^developers/', include('mkt.developers.urls')),

    # Submission.
    ('^developers/submit/app/', include('mkt.submit.urls')),

    # The new hotness.
    ('^hub/', include('mkt.hub.urls')),

    # Misc pages.
    ('', include('mkt.site.urls')),
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
