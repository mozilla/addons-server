from lib.urls_base import *


urlpatterns += patterns('',
    # The old-but-new Marketplace.
    ('^dev/', include('mkt.developers.urls')),

    # The new hotness.
    ('^hub/', include('mkt.hub.urls')),
)


# Marketplace UI Experiments
if getattr(settings, 'POTCH_MARKETPLACE_EXPERIMENTS', False):
    urlpatterns += patterns('',
        ('^marketplace-experiments/', include('mkt.experiments.urls'))
    )
