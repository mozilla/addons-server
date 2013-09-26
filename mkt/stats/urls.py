from django.conf.urls import patterns, url
from django.shortcuts import redirect

from . import api, views

from stats.urls import series_re


# Time series URLs following this pattern:
# /app/{app_slug}/statistics/{series}-{group}-{start}-{end}.{format}
# Also supports in-app URLs:
# /app/{app_slug}/statistics/{inapp}/{series}-{group}-{start}-{end}
# .{format}
inapp = """inapp/(?P<inapp>[^/<>"]+)"""
series = dict((type, '%s-%s' % (type, series_re)) for type in views.SERIES)


stats_api_patterns = patterns('',
    url(r'^stats/global/(?P<metric>[^/]+)/$', api.GlobalStats.as_view(),
        name='global_stats'),
    url(r'^stats/app/(?P<pk>[^/<>"\']+)/(?P<metric>[^/]+)/$',
        api.AppStats.as_view(), name='app_stats'),
)


txn_api_patterns = patterns('',
    url(r'^transaction/(?P<transaction_id>[^/]+)/$',
        api.TransactionAPI.as_view(),
        name='transaction_api'),
)


def sales_stats_report_urls(category='', inapp_flag=False):
    """
    urlpatterns helper builder for views.stats_report urls
    """
    url_patterns = []
    sales_metrics = ['revenue', 'sales', 'refunds']

    inapp_prefix = ''
    inapp_suffix = ''
    if inapp_flag:
        inapp_prefix = inapp + '/'
        inapp_suffix = '_inapp'

    category_prefix = ''
    category_suffix = ''
    if category:
        category_prefix = category + '_'
        category_suffix = category + '/'

    for metric in sales_metrics:
        full_category = '%s%s' % (category_prefix, metric)

        # URL defaults revenue to root, don't explicitly put in url.
        if metric == 'revenue':
            metric = ''

        url_patterns += patterns('',
            url('^%ssales/%s%s$' % (inapp_prefix, category_suffix, metric),
                views.stats_report,
                name='mkt.stats.%s' % full_category + inapp_suffix,
                kwargs={'report': full_category + inapp_suffix})
        )
    return url_patterns


def sales_series_urls(category='', inapp_flag=False):
    """
    urlpatterns helper builder for views.*_series urls
    """
    url_patterns = []
    sales_metrics = ['revenue', 'sales', 'refunds']

    inapp_suffix = ''
    if inapp_flag:
        inapp_suffix = '_inapp'

    # Distinguish between line and column series.
    view = views.finance_line_series
    category_prefix = ''
    if category:
        view = views.finance_column_series
        category_prefix = category + '_'

    for metric in sales_metrics:
        full_category = '%s%s%s' % (category_prefix, metric, inapp_suffix)

        kwargs = {}
        if metric != 'sales':
            # Defaults to sales so does not need primary_field arg.
            kwargs['primary_field'] = metric
        if category:
            kwargs['category_field'] = category

        url_re = series[full_category]
        if inapp_flag:
            url_re = '^%s/sales/%s' % (inapp, series[full_category])

        url_patterns += patterns('',
            url(url_re,
                view,
                name='mkt.stats.%s' % full_category + '_series',
                kwargs=kwargs)
        )
    return url_patterns


app_stats_patterns = patterns('',
    # Overview (not implemented).
    url('^$', views.stats_report, name='mkt.stats.overview',
        kwargs={'report': 'installs'}),
        # kwargs={'report': 'app_overview'}.

    # Installs.
    url('^installs/$', views.stats_report, name='mkt.stats.installs',
        kwargs={'report': 'installs'}),
    url(series['installs'], views.installs_series,
        name='mkt.stats.installs_series'),

    # Usage (not implemented).
    url('^usage/$', views.stats_report, name='mkt.stats.usage',
        kwargs={'report': 'usage'}),
    url(series['usage'], views.usage_series,
        name='mkt.stats.usage_series'),
)

app_stats_patterns += sales_stats_report_urls(category='currency',
                                           inapp_flag=True)
app_stats_patterns += sales_series_urls(category='currency', inapp_flag=True)
app_stats_patterns += sales_stats_report_urls(category='source',
                                              inapp_flag=True)
app_stats_patterns += sales_series_urls(category='source', inapp_flag=True)
app_stats_patterns += sales_stats_report_urls(inapp_flag=True)
app_stats_patterns += sales_series_urls(inapp_flag=True)

app_stats_patterns += sales_stats_report_urls(category='currency')
app_stats_patterns += sales_series_urls(category='currency')
app_stats_patterns += sales_stats_report_urls(category='source')
app_stats_patterns += sales_series_urls(category='source')

app_stats_patterns += sales_stats_report_urls()
app_stats_patterns += sales_series_urls()

# Overall site statistics.
app_site_patterns = patterns('',
    url('^$', lambda r: redirect('mkt.stats.apps_count_new', permanent=False),
        name='mkt.stats.overall')
)

keys = ['apps_count_new', 'apps_count_installed', 'apps_review_count_new',
        'mmo_user_count_total', 'mmo_user_count_new', 'mmo_total_visitors']

urls = []
for key in keys:
    urls.append(url('^%s/$' % key, views.overall,
                name='mkt.stats.%s' % key, kwargs={'report': key}))

app_site_patterns += patterns('', *urls)

all_apps_stats_patterns = patterns('',
    # Landing pages.
    url('^$', views.my_apps_report, name='mkt.stats.my_apps_overview',
        kwargs={'report': 'installs'}),
    url('^installs/$', views.my_apps_report, name='mkt.stats.my_apps_installs',
        kwargs={'report': 'installs'}),

    # Data URL.
    url(series['my_apps'], views.my_apps_series,
        name='mkt.stats.my_apps_series'),
)
