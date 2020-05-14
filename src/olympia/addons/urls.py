from django.conf.urls import include, url

from olympia.amo.views import frontend_view
from olympia.stats.urls import stats_patterns

from . import views


ADDON_ID = r"""(?P<addon_id>[^/<>"']+)"""


# These will all start with /addon/<addon_id>/
detail_patterns = [
    url(r'^$', frontend_view, name='addons.detail'),
    url(r'^license/(?P<version>[^/]+)?', frontend_view, name='addons.license'),

    url(r'^reviews/', include('olympia.ratings.urls')),
    url(r'^statistics/', include(stats_patterns)),
    url(r'^versions/', include('olympia.versions.urls')),
]


urlpatterns = [
    # URLs for a single add-on.
    url(r'^addon/%s/' % ADDON_ID, include(detail_patterns)),

    url(r'^find-replacement/$', views.find_replacement_addon,
        name='addons.find_replacement'),

    # frontend block view
    url(r'^blocked-addon/%s/' % ADDON_ID, frontend_view,
        name='blocklist.block'),
]
