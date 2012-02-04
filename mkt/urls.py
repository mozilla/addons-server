from lib.urls_base import *


# Marketplace UI Experiments
if settings.POTCH_MARKETPLACE_EXPERIMENTS:
    urlpatterns += patterns('',
        ('^marketplace-experiments/', include('mkt.experiments.urls'))
    )

