from django.conf.urls import include, patterns, url
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import redirect
from django.views.decorators.cache import cache_page

from olympia.stats.urls import stats_patterns
from . import buttons
from . import views

ADDON_ID = r"""(?P<addon_id>[^/<>"']+)"""


# These will all start with /addon/<addon_id>/
detail_patterns = [
    url('^$', views.addon_detail, name='addons.detail'),
    url('^more$', views.addon_detail, name='addons.detail_more'),
    url('^eula/(?P<file_id>\d+)?$', views.eula, name='addons.eula'),
    url('^license/(?P<version>[^/]+)?', views.license, name='addons.license'),
    url('^privacy/', views.privacy, name='addons.privacy'),
    url('^abuse/', views.report_abuse, name='addons.abuse'),

    url('^developers$', views.developers,
        {'page': 'developers'}, name='addons.meet'),
    url('^contribute/roadblock/', views.developers,
        {'page': 'roadblock'}, name='addons.roadblock'),
    url('^contribute/installed/', views.developers,
        {'page': 'installed'}, name='addons.installed'),
    url('^contribute/thanks',
        csrf_exempt(lambda r, addon_id: redirect('addons.detail', addon_id)),
        name='addons.thanks'),
    url('^contribute/$', views.contribute, name='addons.contribute'),
    url('^contribute/(?P<status>cancel|complete)$', views.paypal_result,
        name='addons.paypal'),

    url('^about$',
        lambda r, addon_id: redirect('addons.installed',
                                     addon_id, permanent=True),
        name='addons.about'),

    url('^reviews/', include('olympia.reviews.urls')),
    url('^statistics/', include(stats_patterns)),
    url('^versions/', include('olympia.versions.urls')),
]


urlpatterns = patterns(
    '',
    # Promo modules for the homepage
    url('^i/promos$', views.homepage_promos, name='addons.homepage_promos'),

    # See https://github.com/mozilla/addons-server/issues/3130
    # Hardcode because there is no relation from blocklist items and the
    # add-on they block :-(
    url('^addon/icloud-bookmarks/$', views.icloud_bookmarks_redirect,
        name='addons.icloudbookmarksredirect'),

    # URLs for a single add-on.
    ('^addon/%s/' % ADDON_ID, include(detail_patterns)),

    # Button messages to be used by JavaScript.
    # Should always be called with a cache-busting querystring.
    url('^addons/buttons\.js$',
        cache_page(60 * 60 * 24 * 365)(buttons.js),
        name='addons.buttons.js'),

    # Remora EULA and Privacy policy URLS
    ('^addons/policy/0/(?P<addon_id>\d+)/(?P<file_id>\d+)',
     lambda r, addon_id, file_id: redirect('addons.eula',
                                           addon_id, file_id, permanent=True)),
    ('^addons/policy/0/(?P<addon_id>\d+)/',
     lambda r, addon_id: redirect('addons.privacy',
                                  addon_id, permanent=True)),

    ('^versions/license/(\d+)$', views.license_redirect),
)
