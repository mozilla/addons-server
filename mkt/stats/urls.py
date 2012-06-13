from django.conf.urls.defaults import include, patterns, url

import addons.views
from . import views

from stats.urls import series_re

series = dict((type, '%s-%s' % (type, series_re)) for type in views.SERIES)

urlpatterns = patterns('',
    # This will eventually be kwargs={'report': 'app_overview'}.
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

    url('^sales/currency/$', views.stats_report,
        name='mkt.stats.currency_revenue',
        kwargs={'report': 'currency_revenue'}),
    url('^sales/currency/sales/$', views.stats_report,
        name='mkt.stats.currency_sales',
        kwargs={'report': 'currency_sales'}),
    url('^sales/currency/refunds/$', views.stats_report,
        name='mkt.stats.currency_refunds',
        kwargs={'report': 'currency_refunds'}),

    url('^sales/source/$', views.stats_report,
        name='mkt.stats.source_revenue',
        kwargs={'report': 'source_revenue'}),
    url('^sales/source/sales/$', views.stats_report,
        name='mkt.stats.source_sales',
        kwargs={'report': 'source_sales'}),
    url('^sales/source/refunds/$', views.stats_report,
        name='mkt.stats.source_refunds',
        kwargs={'report': 'source_refunds'}),

    # Time series URLs following this pattern:
    # /app/{app_slug}/statistics/{series}-{group}-{start}-{end}.{format}
    url(series['installs'], views.installs_series,
        name='mkt.stats.installs_series'),
    url(series['usage'], views.usage_series,
        name='mkt.stats.usage_series'),

    # Currency breakdown.
    url(series['currency_revenue'], views.currency_series,
        name='mkt.stats.currency_revenue_series',
        kwargs={'primary_field': 'revenue'}),
    url(series['currency_sales'], views.currency_series,
        name='mkt.stats.currency_sales_series'),
    url(series['currency_refunds'], views.currency_series,
        name='mkt.stats.currency_refunds_series',
        kwargs={'primary_field': 'refunds'}),

    # Source breakdown.
    url(series['source_revenue'], views.source_series,
        name='mkt.stats.source_revenue_series',
        kwargs={'primary_field': 'revenue'}),
    url(series['source_sales'], views.source_series,
        name='mkt.stats.source_sales_series',
        kwargs={'primary_field': 'count'}),
    url(series['source_refunds'], views.source_series,
        name='mkt.stats.source_refunds_series',
        kwargs={'primary_field': 'refunds'}),

    url(series['revenue'], views.revenue_series,
        name='mkt.stats.revenue_series'),
    url(series['sales'], views.sales_series,
        name='mkt.stats.sales_series'),
    url(series['refunds'], views.refunds_series,
        name='mkt.stats.refunds_series'),
)
