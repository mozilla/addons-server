from django.conf.urls.defaults import patterns, url
from versions.feeds import VersionsRss

from . import views

urlpatterns = patterns('',
    url('^$', views.version_list, name='addons.versions'),
    url('^format:rss$', VersionsRss(), name='addons.versions.rss'),
    url('^(?P<version_num>[^/]+)$', views.version_detail,
        name='addons.versions'),
)

download_patterns = patterns('',
    # .* at the end to match filenames.
    # /file/:id/type:attachment
    url('^file/(?P<file_id>\d+)/(?:type:(?P<type>\w+))?.*',
        views.download_file, name='downloads.file'),

    # /latest/1865/type:xpi/platform:5
    url('^latest/(?P<addon_id>\d+)/'
        '(?:type:(?P<type>\w+)/)?(?:platform:(?P<platform>\d+)/)?.*',
        views.download_latest, name='downloads.latest'),
)
