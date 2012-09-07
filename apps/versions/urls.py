from django.conf.urls import patterns, url
from versions.feeds import VersionsRss

from addons.urls import ADDON_ID
from . import views

urlpatterns = patterns('',
    url('^$', views.version_list, name='addons.versions'),
    url('^format:rss$', VersionsRss(), name='addons.versions.rss'),
    url('^(?P<version_num>[^/]+)$', views.version_detail,
        name='addons.versions'),
    url('^(?P<version_num>[^/]+)/updateinfo/$', views.update_info,
        name='addons.versions.update_info'),
)

download_patterns = patterns('',
    # .* at the end to match filenames.
    # /file/:id/type:attachment
    url('^file/(?P<file_id>\d+)(?:/type:(?P<type>\w+))?(?:/.*)?',
        views.download_file, name='downloads.file'),

    # /latest/1865/type:xpi/platform:5
    url('^latest/%s/(?:type:(?P<type>\w+)/)?'
        '(?:platform:(?P<platform>\d+)/)?.*' % ADDON_ID,
        views.download_latest, name='downloads.latest'),

    url('^watermarked/(?P<file_id>\d+)?(?:/.*)?',
        views.download_watermarked, name='downloads.watermarked'),
)
