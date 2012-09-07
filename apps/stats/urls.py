from django.conf.urls import patterns, url
from django.shortcuts import redirect

from . import views

group_re = '(?P<group>' + '|'.join(views.SERIES_GROUPS) + ')'
group_date_re = '(?P<group>' + '|'.join(views.SERIES_GROUPS_DATE) + ')'
range_re = '(?P<start>\d{8})-(?P<end>\d{8})'
format_re = '(?P<format>' + '|'.join(views.SERIES_FORMATS) + ')'
series_re = '%s-%s\.%s$' % (group_re, range_re, format_re)
series = dict((type, '%s-%s' % (type, series_re)) for type in views.SERIES)
global_series = dict((type, '%s-%s' % (type, series_re))
                     for type in views.GLOBAL_SERIES)
collection_series = dict((type, '%s-%s' % (type, series_re))
                         for type in views.COLLECTION_SERIES)

urlpatterns = patterns('',
    url('^$', lambda r: redirect('stats.addons_in_use', permanent=False),
        name='stats.dashboard'),
    url('^site%s/%s$' % (format_re, group_date_re),
        views.site, name='stats.site'),
    url('^site-%s' % series_re, views.site, name='stats.site.new'),
    url('^fake-%s' % series_re, views.fake_collection_stats),
    url('^collection/(?P<uuid>[\w-]+).%s$' % (format_re),
        views.collection, name='stats.collection'),

    # global series urls.
    url(global_series['addons_in_use'], views.site_series,
        kwargs={'field': 'addons_in_use'}),
    url(global_series['addons_updated'], views.site_series,
        kwargs={'field': 'addons_updated'}),
    url(global_series['addons_downloaded'], views.site_series,
        kwargs={'field': 'addons_downloaded'}),
    url(global_series['addons_created'], views.site_series,
        kwargs={'field': 'addons_created'}),
    url(global_series['reviews_created'], views.site_series,
        kwargs={'field': 'reviews_created'}),
    url(global_series['collections_created'], views.site_series,
        kwargs={'field': 'collections_created'}),
    url(global_series['users_created'], views.site_series,
        kwargs={'field': 'users_created'}),

    # global series urls.
    url('^addons_in_use/$', views.site_stats_report,
        kwargs={'report': 'addons_in_use'}, name='stats.addons_in_use'),
    url('^addons_updated/$', views.site_stats_report,
        kwargs={'report': 'addons_updated'}, name='stats.addons_updated'),
    url('^addons_downloaded/$', views.site_stats_report,
        kwargs={'report': 'addons_downloaded'}, name='stats.addons_downloaded'),
    url('^addons_created/$', views.site_stats_report,
        kwargs={'report': 'addons_created'}, name='stats.addons_created'),
    url('^reviews_created/$', views.site_stats_report,
        kwargs={'report': 'reviews_created'}, name='stats.reviews_created'),
    url('^collections_created/$', views.site_stats_report,
        kwargs={'report': 'collections_created'}, name='stats.collections_created'),
    url('^users_created/$', views.site_stats_report,
        kwargs={'report': 'users_created'}, name='stats.users_created'),
)

collection_stats_urls = patterns('',
    url(collection_series['subscribers'], views.collection_series,
        kwargs={'field': 'subscribers'}),
    url(collection_series['ratings'], views.collection_series,
        kwargs={'field': 'ratings'}),
    url(collection_series['downloads'], views.collection_series,
        kwargs={'field': 'downloads'}),

    url('^$', views.collection_report, name='collections.stats',
        kwargs={'report': 'subscribers'}),
    url('^subscribers/$', views.collection_report,
        name='collections.stats.subscribers',
        kwargs={'report': 'subscribers'}),
    url(collection_series['subscribers'], views.collection_stats,
        name='collections.stats.subscribers_series'),
    url('^ratings/$', views.collection_report,
        name='collections.stats.ratings',
        kwargs={'report': 'ratings'}),
    url(collection_series['ratings'], views.collection_stats,
        name='collections.stats.ratings_series'),
    url('^downloads/$', views.collection_report,
        name='collections.stats.downloads',
        kwargs={'report': 'downloads'}),
    url(collection_series['downloads'], views.collection_stats,
        name='collections.stats.downloads_series'),
)

# Addon specific stats.
stats_patterns = patterns('',
    # page URLs
    url('^$', views.stats_report, name='stats.overview',
        kwargs={'report': 'overview'}),
    url('^downloads/$', views.stats_report, name='stats.downloads',
        kwargs={'report': 'downloads'}),
    url('^downloads/sources/$', views.stats_report, name='stats.sources',
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
    url('^usage/os/$', views.stats_report, name='stats.os',
        kwargs={'report': 'os'}),
    url('^contributions/$', views.stats_report, name='stats.contributions',
        kwargs={'report': 'contributions'}),


    # time series URLs following this pattern:
    # /addon/{addon_id}/statistics/{series}-{group}-{start}-{end}.{format}
    url(series['overview'], views.overview_series,
        name='stats.overview_series'),
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
)
