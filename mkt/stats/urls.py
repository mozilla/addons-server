from django.conf.urls.defaults import include, patterns, url

import addons.views
from . import views

from stats.urls import series_re

series = dict((type, '%s-%s' % (type, series_re)) for type in views.SERIES)

urlpatterns = patterns('',
    # This will eventually be kwargs={'report': 'app_overview'}
    url('^$', views.stats_report, name='mkt.stats.overview',
        kwargs={'report': 'installs'}),
    url('^installs/$', views.stats_report, name='mkt.stats.installs',
        kwargs={'report': 'installs'}),
    url('^usage/$', views.stats_report, name='mkt.stats.usage',
        kwargs={'report': 'usage'}),

    url('^sales/$', views.stats_report, name='mkt.stats.revenue',
        kwargs={'report': 'revenue'}),
    url('^sales/sales/$', views.stats_report, name='mkt.stats.sales',
        kwargs={'report': 'sales'}),
    url('^sales/refunds/$', views.stats_report, name='mkt.stats.refunds',
        kwargs={'report': 'refunds'}),

    # time series URLs following this pattern:
    # /app/{app_slug}/statistics/{series}-{group}-{start}-{end}.{format}
    url(series['app_overview'], views.overview_series,
        name='mkt.stats.overview_series'),
    url(series['installs'], views.installs_series,
        name='mkt.stats.installs_series'),
    url(series['usage'], views.usage_series,
        name='mkt.stats.usage_series'),

    url(series['revenue'], views.sales_series,
        name='mkt.stats.revenue_series'),
    url(series['sales'], views.sales_series,
        name='mkt.stats.sales_series'),
    url(series['refunds'], views.sales_series,
        name='mkt.stats.refunds_series'),
)
