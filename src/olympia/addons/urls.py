from django.urls import include, re_path

from olympia.amo.views import frontend_view
from olympia.stats.urls import stats_patterns

from . import views


ADDON_ID = r"""(?P<addon_id>[^/<>"']+)"""

# These will all start with /addon/<addon_id>/
detail_patterns = [
    re_path(r'^$', frontend_view, name='addons.detail'),
    re_path(r'^license/(?P<version>[^/]+)?', frontend_view, name='addons.license'),
    re_path(r'^reviews/', include('olympia.ratings.urls')),
    re_path(r'^statistics/', include(stats_patterns)),
    re_path(r'^versions/', include('olympia.versions.urls')),
]

urlpatterns = [
    # URLs for a single add-on.
    re_path(r'^addon/%s/' % ADDON_ID, include(detail_patterns)),
    re_path(
        r'^find-replacement/$',
        views.find_replacement_addon,
        name='addons.find_replacement',
    ),
    # frontend block view
    re_path(r'^blocked-addon/%s/' % ADDON_ID, frontend_view, name='blocklist.block'),
]
