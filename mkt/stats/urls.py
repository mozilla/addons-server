from django.conf.urls import patterns, url

from . import api


stats_api_patterns = patterns('',
    url(r'^stats/global/totals/$', api.GlobalStatsTotal.as_view(),
        name='global_stats_total'),
    url(r'^stats/global/(?P<metric>[^/]+)/$', api.GlobalStats.as_view(),
        name='global_stats'),
    url(r'^stats/app/(?P<pk>[^/<>"\']+)/totals/$',
        api.AppStatsTotal.as_view(), name='app_stats_total'),
    url(r'^stats/app/(?P<pk>[^/<>"\']+)/(?P<metric>[^/]+)/$',
        api.AppStats.as_view(), name='app_stats'),
)


txn_api_patterns = patterns('',
    url(r'^transaction/(?P<transaction_id>[^/]+)/$',
        api.TransactionAPI.as_view(),
        name='transaction_api'),
)
