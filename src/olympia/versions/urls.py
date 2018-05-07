from django.conf.urls import url

from olympia.addons.urls import ADDON_ID
from olympia.versions.feeds import VersionsRss

from . import views


urlpatterns = [
    url('^$',
        views.version_list, name='addons.versions'),
    url('^format:rss$',
        VersionsRss(), name='addons.versions.rss'),
    url('^(?P<version_num>[^/]+)$', views.version_detail,
        name='addons.versions'),
    url('^(?P<version_num>[^/]+)/updateinfo/$', views.update_info,
        name='addons.versions.update_info'),
]

download_patterns = [
    # .* at the end to match filenames.
    # /file/:id/type:attachment
    url('^file/(?P<file_id>\d+)(?:/type:(?P<type>\w+))?(?:/.*)?',
        views.download_file, name='downloads.file'),

    url('^source/(?P<version_id>\d+)',
        views.download_source, name='downloads.source'),

    # /latest/1865/type:xpi/platform:5
    url('^latest/%s/(?:type:(?P<type>\w+)/)?'
        '(?:platform:(?P<platform>\d+)/)?.*' % ADDON_ID,
        views.download_latest, name='downloads.latest'),
]
