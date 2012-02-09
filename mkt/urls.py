from lib.urls_base import *


urlpatterns += patterns('',
    ('^hub/', include('mkt.hub.urls')),
)


# Marketplace UI Experiments
if settings.POTCH_MARKETPLACE_EXPERIMENTS:
    urlpatterns += patterns('',
        ('^marketplace-experiments/', include('mkt.experiments.urls'))
    )
