from django.conf.urls.defaults import patterns, url

from . import views


group_re = '(?P<group>' + '|'.join(views.SERIES_GROUPS) + ')'
range_re = '(?P<start>\d{8})-(?P<end>\d{8})'
format_re = '(?P<format>' + '|'.join(views.SERIES_FORMATS) + ')'
series = dict((type, '^%s-%s-%s\.%s$' % (type, group_re, range_re, format_re))
              for type in views.SERIES)

urlpatterns = patterns('',
    # page URLs
    url('^$', views.stats_report, name='stats.overview', 
        kwargs={'report': 'overview'}),
    url('^downloads/$', views.stats_report, name='stats.downloads',
        kwargs={'report': 'downloads'}),
    url('^downloads/sources/$', views.stats_report, name='stats.downloads',
        kwargs={'report': 'sources'}),
    url('^usage/$', views.stats_report, name='stats.usage',
        kwargs={'report': 'usage'}),
    url('^usage/languages/$', views.stats_report, name='stats.locales',
        kwargs={'report': 'locales'}),
    url('^usage/versions/$', views.stats_report, name='stats.versions',
        kwargs={'report': 'versions'}),
    url('^usage/status/$', views.stats_report, name='stats.statuses',
        kwargs={'report': 'statuses'}),
    url('^usage/applications/$', views.stats_report, name='stats.apps',
        kwargs={'report': 'apps'}),
    url('^usage/os/$', views.stats_report, name='stats.usage.os',
        kwargs={'report': 'os'}),
    url('^contributions/$', views.stats_report, name='stats.contributions',
        kwargs={'report': 'contributions'}),



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
