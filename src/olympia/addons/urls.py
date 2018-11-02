from django.conf.urls import include, url
from django.shortcuts import redirect

from olympia.stats.urls import stats_patterns

from . import views


ADDON_ID = r"""(?P<addon_id>[^/<>"']+)"""


# These will all start with /addon/<addon_id>/
detail_patterns = [
    url(r'^$', views.addon_detail, name='addons.detail'),
    url(r'^more$', views.addon_detail, name='addons.detail_more'),
    url(r'^eula/(?P<file_id>\d+)?$', views.eula, name='addons.eula'),
    url(r'^license/(?P<version>[^/]+)?', views.license, name='addons.license'),
    url(r'^privacy/', views.privacy, name='addons.privacy'),
    url(r'^abuse/', views.report_abuse, name='addons.abuse'),

    url(r'^reviews/', include('olympia.ratings.urls')),
    url(r'^statistics/', include(stats_patterns)),
    url(r'^versions/', include('olympia.versions.urls')),

    # Old contribution urls
    url(r'^developers$',
        lambda r, addon_id: redirect('addons.detail',
                                     addon_id, permanent=True),
        name='addons.meet'),
    url(r'^contribute/roadblock/',
        lambda r, addon_id: redirect('addons.detail',
                                     addon_id, permanent=True),
        name='addons.roadblock'),
    url(r'^contribute/installed/',
        lambda r, addon_id: redirect('addons.detail',
                                     addon_id, permanent=True),
        name='addons.installed'),
    url(r'^contribute/thanks',
        lambda r, addon_id: redirect('addons.detail',
                                     addon_id, permanent=True),
        name='addons.thanks'),
    url(r'^contribute/$',
        lambda r, addon_id: redirect('addons.detail',
                                     addon_id, permanent=True),
        name='addons.contribute'),
    url(r'^contribute/(?P<status>cancel|complete)$',
        lambda r, addon_id, status: redirect('addons.detail',
                                             addon_id, permanent=True),
        name='addons.contribute_status'),
    url(r'^about$',
        lambda r, addon_id: redirect('addons.detail',
                                     addon_id, permanent=True),
        name='addons.about'),
]


urlpatterns = [
    # Promo modules for the homepage
    url(r'^i/promos$', views.homepage_promos, name='addons.homepage_promos'),

    # See https://github.com/mozilla/addons-server/issues/3130
    # Hardcode because there is no relation from blocklist items and the
    # add-on they block :-(
    url(r'^addon/icloud-bookmarks/$', views.icloud_bookmarks_redirect,
        name='addons.icloudbookmarksredirect'),

    # URLs for a single add-on.
    url(r'^addon/%s/' % ADDON_ID, include(detail_patterns)),

    # Remora EULA and Privacy policy URLS
    url(r'^addons/policy/0/(?P<addon_id>\d+)/(?P<file_id>\d+)',
        lambda r, addon_id, file_id: redirect(
            'addons.eula', addon_id, file_id, permanent=True)),
    url(r'^addons/policy/0/(?P<addon_id>\d+)/',
        lambda r, addon_id: redirect(
            'addons.privacy', addon_id, permanent=True)),

    url(r'^versions/license/(\d+)$', views.license_redirect),

    url(r'^find-replacement/$', views.find_replacement_addon,
        name='addons.find_replacement'),
]
