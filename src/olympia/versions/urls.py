from django.conf.urls import url

from olympia.addons.urls import ADDON_ID
from olympia.versions.feeds import VersionsRss

from . import views


urlpatterns = [
    url(r'^$',
        views.version_list, name='addons.versions'),
    url(r'^format:rss$',
        VersionsRss(), name='addons.versions.rss'),
    url(r'^(?P<version_num>[^/]+)$', views.version_detail,
        name='addons.versions'),
    url(r'^(?P<version_num>[^/]+)/updateinfo/$', views.update_info,
        name='addons.versions.update_info'),
]

download_patterns = [
    # .* at the end to match filenames.
    # /file/:id/type:attachment
    url(r'^file/(?P<file_id>\d+)(?:/type:(?P<type>\w+))?(?:/.*)?',
        views.download_file, name='downloads.file'),

    url(r'^source/(?P<version_id>\d+)',
        views.download_source, name='downloads.source'),

    # /latest/1865/type:xpi/platform:5
    url(r'^latest/%s/(?:type:(?P<type>\w+)/)?'
        r'(?:platform:(?P<platform>\d+)/)?.*' % ADDON_ID,
        views.download_latest, name='downloads.latest'),
]
