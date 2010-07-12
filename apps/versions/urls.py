from django.conf.urls.defaults import patterns, url
from versions.feeds import VersionsRss

from . import views

urlpatterns = patterns('',
    url('^$', views.version_list, name='addons.versions'),
    url('^format:rss$', VersionsRss(), name='addons.versions.rss'),
    url('^(?P<version_num>[^/]+)$', views.version_detail,
        name='addons.versions'),
)
