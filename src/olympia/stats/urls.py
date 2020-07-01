from django.conf.urls import url

from . import views


group_re = r'(?P<group>' + '|'.join(views.SERIES_GROUPS) + ')'
group_date_re = r'(?P<group>' + '|'.join(views.SERIES_GROUPS_DATE) + ')'
range_re = r'(?P<start>\d{8})-(?P<end>\d{8})'
format_re = r'(?P<format>' + '|'.join(views.SERIES_FORMATS) + ')'
series_re = r'%s-%s\.%s$' % (group_re, range_re, format_re)
series = dict((type, r'^%s-%s' % (type, series_re)) for type in views.SERIES)

# Addon specific stats.
stats_patterns = [
    # page URLs
    url(r'^$', views.stats_report, name='stats.overview',
        kwargs={'report': 'overview'}),

    url(r'^downloads/$', views.stats_report, name='stats.downloads',
        kwargs={'report': 'downloads'}),

    url(r'^downloads/sources/$', views.stats_report, name='stats.sources',
        kwargs={'report': 'sources'}),

    url(r'^usage/$', views.stats_report, name='stats.usage',
        kwargs={'report': 'usage'}),

    url(r'^usage/languages/$', views.stats_report, name='stats.locales',
        kwargs={'report': 'locales'}),

    url(r'^usage/versions/$', views.stats_report, name='stats.versions',
        kwargs={'report': 'versions'}),

    url(r'^usage/applications/$', views.stats_report, name='stats.apps',
        kwargs={'report': 'apps'}),

    url(r'^usage/os/$', views.stats_report, name='stats.os',
        kwargs={'report': 'os'}),

    url(r'^usage/countries/$', views.stats_report, name='stats.countries',
        kwargs={'report': 'countries'}),

    # time series URLs following this pattern:
    # /addon/{addon_id}/statistics/{series}-{group}-{start}-{end}.{format}
    url(series['overview'], views.overview_series,
        name='stats.overview_series'),

    url(series['downloads'], views.downloads_series,
        name='stats.downloads_series'),

    url(series['usage'], views.usage_series, name='stats.usage_series'),

    url(series['sources'], views.sources_series, name='stats.sources_series'),

    url(series['os'], views.usage_breakdown_series,
        name='stats.os_series', kwargs={'field': 'oses'}),

    url(series['locales'], views.usage_breakdown_series,
        name='stats.locales_series', kwargs={'field': 'locales'}),

    url(series['versions'], views.usage_breakdown_series,
        name='stats.versions_series', kwargs={'field': 'versions'}),

    url(series['apps'], views.usage_breakdown_series,
        name='stats.apps_series', kwargs={'field': 'applications'}),

    url(series['countries'], views.usage_breakdown_series,
        name='stats.countries_series', kwargs={'field': 'countries'}),
]
