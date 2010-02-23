from django.conf.urls.defaults import patterns, url

from . import views


group_re = '(?P<group>' + '|'.join(views.SERIES_GROUPS) + ')'
range_re = '(?P<start>\d{8})-(?P<end>\d{8})'
format_re = '(?P<format>' + '|'.join(views.SERIES_FORMATS) + ')'
series = dict((type, '^%s-%s-%s\.%s$' % (type, group_re, range_re, format_re))
              for type in views.SERIES)

urlpatterns = patterns('',
    # time series URLs following this pattern:
    # /addon/{addon_id}/statistics/{series}-{group}-{start}-{end}.{format}
    url(series['downloads'], views.downloads_series,
        name='stats.downloads_series'),
    url(series['usage'], views.usage_series,
        name='stats.usage_series'),
    url(series['contributions'], views.contributions_series,
        name='stats.contributions_series'),
    url(series['sources'], views.sources_series,
        name='stats.sources_series'),
    url(series['os'], views.usage_breakdown_series,
        name='stats.os_series', kwargs={'field': 'oses'}),
    url(series['locales'], views.usage_breakdown_series,
        name='stats.locales_series', kwargs={'field': 'locales'}),
    url(series['statuses'], views.usage_breakdown_series,
        name='stats.statuses_series', kwargs={'field': 'statuses'}),
    url(series['versions'], views.usage_breakdown_series,
        name='stats.versions_series', kwargs={'field': 'versions'}),
    url(series['apps'], views.usage_breakdown_series,
        name='stats.apps_series', kwargs={'field': 'applications'}),

    # special case time series
    url('^contributions-detail-%s\.%s$' % (range_re, format_re),
        views.contributions_detail, name='stats.contributions_detail'),
)
