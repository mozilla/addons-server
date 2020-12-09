from django.urls import re_path

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
    re_path(
        r'^$', views.stats_report, name='stats.overview', kwargs={'report': 'overview'}
    ),
    re_path(
        r'^downloads/$',
        views.stats_report,
        name='stats.downloads',
        kwargs={'report': 'downloads'},
    ),
    re_path(
        r'^downloads/sources/$',
        views.stats_report,
        name='stats.sources',
        kwargs={'report': 'sources'},
    ),
    re_path(
        r'^downloads/mediums/$',
        views.stats_report,
        name='stats.mediums',
        kwargs={'report': 'mediums'},
    ),
    re_path(
        r'^downloads/contents/$',
        views.stats_report,
        name='stats.contents',
        kwargs={'report': 'contents'},
    ),
    re_path(
        r'^downloads/campaigns/$',
        views.stats_report,
        name='stats.campaigns',
        kwargs={'report': 'campaigns'},
    ),
    re_path(
        r'^usage/$', views.stats_report, name='stats.usage', kwargs={'report': 'usage'}
    ),
    re_path(
        r'^usage/languages/$',
        views.stats_report,
        name='stats.locales',
        kwargs={'report': 'locales'},
    ),
    re_path(
        r'^usage/versions/$',
        views.stats_report,
        name='stats.versions',
        kwargs={'report': 'versions'},
    ),
    re_path(
        r'^usage/applications/$',
        views.stats_report,
        name='stats.apps',
        kwargs={'report': 'apps'},
    ),
    re_path(
        r'^usage/os/$', views.stats_report, name='stats.os', kwargs={'report': 'os'}
    ),
    re_path(
        r'^usage/countries/$',
        views.stats_report,
        name='stats.countries',
        kwargs={'report': 'countries'},
    ),
    # time series URLs following this pattern:
    # /addon/{addon_id}/statistics/{series}-{group}-{start}-{end}.{format}
    re_path(series['overview'], views.overview_series, name='stats.overview_series'),
    re_path(series['downloads'], views.downloads_series, name='stats.downloads_series'),
    re_path(series['usage'], views.usage_series, name='stats.usage_series'),
    re_path(
        series['sources'],
        views.download_breakdown_series,
        name='stats.sources_series',
        kwargs={'source': 'sources'},
    ),
    re_path(
        series['mediums'],
        views.download_breakdown_series,
        name='stats.mediums_series',
        kwargs={'source': 'mediums'},
    ),
    re_path(
        series['contents'],
        views.download_breakdown_series,
        name='stats.contents_series',
        kwargs={'source': 'contents'},
    ),
    re_path(
        series['campaigns'],
        views.download_breakdown_series,
        name='stats.campaigns_series',
        kwargs={'source': 'campaigns'},
    ),
    re_path(
        series['os'],
        views.usage_breakdown_series,
        name='stats.os_series',
        kwargs={'field': 'oses'},
    ),
    re_path(
        series['locales'],
        views.usage_breakdown_series,
        name='stats.locales_series',
        kwargs={'field': 'locales'},
    ),
    re_path(
        series['versions'],
        views.usage_breakdown_series,
        name='stats.versions_series',
        kwargs={'field': 'versions'},
    ),
    re_path(
        series['apps'],
        views.usage_breakdown_series,
        name='stats.apps_series',
        kwargs={'field': 'applications'},
    ),
    re_path(
        series['countries'],
        views.usage_breakdown_series,
        name='stats.countries_series',
        kwargs={'field': 'countries'},
    ),
]
