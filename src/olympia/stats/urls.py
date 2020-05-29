from django.conf.urls import url

from . import views


group_re = r'(?P<group>' + '|'.join(views.SERIES_GROUPS) + ')'
group_date_re = r'(?P<group>' + '|'.join(views.SERIES_GROUPS_DATE) + ')'
range_re = r'(?P<start>\d{8})-(?P<end>\d{8})'
format_re = r'(?P<format>' + '|'.join(views.SERIES_FORMATS) + ')'
series_re = r'%s-%s\.%s$' % (group_re, range_re, format_re)
series = dict((type, r'^%s-%s' % (type, series_re)) for type in views.SERIES)
beta_series = dict(
    (type, r'^beta/%s-%s' % (type, series_re)) for type in views.BETA_SERIES
)


# Addon specific stats.
stats_patterns = [
    # page URLs
    url(r'^$', views.stats_report, name='stats.overview',
        kwargs={'report': 'overview'}),
    url(r'^beta/$', views.stats_report, name='stats.overview.beta',
        kwargs={'report': 'overview', 'beta': True}),

    url(r'^downloads/$', views.stats_report, name='stats.downloads',
        kwargs={'report': 'downloads'}),
    url(r'^beta/downloads/$', views.stats_report, name='stats.downloads.beta',
        kwargs={'report': 'downloads', 'beta': True}),

    url(r'^downloads/sources/$', views.stats_report, name='stats.sources',
        kwargs={'report': 'sources'}),
    url(r'^beta/downloads/sources/$', views.stats_report,
        name='stats.sources.beta', kwargs={'report': 'sources', 'beta': True}),

    url(r'^usage/$', views.stats_report, name='stats.usage',
        kwargs={'report': 'usage'}),
    url(r'^beta/usage/$', views.stats_report, name='stats.usage.beta',
        kwargs={'report': 'usage', 'beta': True}),

    url(r'^usage/languages/$', views.stats_report, name='stats.locales',
        kwargs={'report': 'locales'}),
    url(r'^beta/usage/languages/$', views.stats_report,
        name='stats.locales.beta', kwargs={'report': 'locales', 'beta': True}),

    url(r'^usage/versions/$', views.stats_report, name='stats.versions',
        kwargs={'report': 'versions'}),
    url(r'^beta/usage/versions/$', views.stats_report,
        name='stats.versions.beta',
        kwargs={'report': 'versions', 'beta': True}),

    url(r'^usage/status/$', views.stats_report, name='stats.statuses',
        kwargs={'report': 'statuses'}),

    url(r'^usage/applications/$', views.stats_report, name='stats.apps',
        kwargs={'report': 'apps'}),
    url(r'^beta/usage/applications/$', views.stats_report,
        name='stats.apps.beta', kwargs={'report': 'apps', 'beta': True}),

    url(r'^usage/os/$', views.stats_report, name='stats.os',
        kwargs={'report': 'os'}),
    url(r'^beta/usage/os/$', views.stats_report, name='stats.os.beta',
        kwargs={'report': 'os', 'beta': True}),

    url(r'^beta/usage/countries/$', views.stats_report,
        name='stats.countries.beta',
        kwargs={'report': 'countries', 'beta': True}),

    # time series URLs following this pattern:
    # /addon/{addon_id}/statistics/{series}-{group}-{start}-{end}.{format}
    url(series['overview'], views.overview_series,
        name='stats.overview_series'),
    url(beta_series['overview'], views.overview_series,
        name='stats.overview_series.beta', kwargs={'beta': True}),

    url(series['downloads'], views.downloads_series,
        name='stats.downloads_series'),
    url(beta_series['downloads'], views.downloads_series,
        name='stats.downloads_series.beta', kwargs={'beta': True}),

    url(series['usage'], views.usage_series, name='stats.usage_series'),
    url(beta_series['usage'], views.usage_series,
        name='stats.usage_series.beta', kwargs={'beta': True}),

    url(series['sources'], views.sources_series, name='stats.sources_series'),
    url(beta_series['sources'], views.sources_series,
        name='stats.sources_series.beta', kwargs={'beta': True}),

    url(series['os'], views.usage_breakdown_series,
        name='stats.os_series', kwargs={'field': 'oses'}),
    url(beta_series['os'], views.usage_breakdown_series,
        name='stats.os_series.beta', kwargs={'field': 'oses', 'beta': True}),

    url(series['locales'], views.usage_breakdown_series,
        name='stats.locales_series', kwargs={'field': 'locales'}),
    url(beta_series['locales'], views.usage_breakdown_series,
        name='stats.locales_series.beta',
        kwargs={'field': 'locales', 'beta': True}),

    url(series['statuses'], views.usage_breakdown_series,
        name='stats.statuses_series', kwargs={'field': 'statuses'}),

    url(series['versions'], views.usage_breakdown_series,
        name='stats.versions_series', kwargs={'field': 'versions'}),
    url(beta_series['versions'], views.usage_breakdown_series,
        name='stats.versions_series.beta',
        kwargs={'field': 'versions', 'beta': True}),

    url(series['apps'], views.usage_breakdown_series,
        name='stats.apps_series', kwargs={'field': 'applications'}),
    url(beta_series['apps'], views.usage_breakdown_series,
        name='stats.apps_series.beta',
        kwargs={'field': 'applications', 'beta': True}),

    url(beta_series['countries'], views.usage_breakdown_series,
        name='stats.countries_series.beta',
        kwargs={'field': 'countries', 'beta': True}),
]
