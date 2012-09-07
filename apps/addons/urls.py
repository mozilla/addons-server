from django.conf.urls import include, patterns, url
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import redirect

from reviews.urls import review_patterns
from stats.urls import stats_patterns
from . import views

ADDON_ID = r"""(?P<addon_id>[^/<>"']+)"""


# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
    url('^$', views.addon_detail, name='addons.detail'),
    url('^more$', views.addon_detail, name='addons.detail_more'),
    url('^eula/(?P<file_id>\d+)?$', views.eula, name='addons.eula'),
    url('^license/(?P<version>[^/]+)?', views.license, name='addons.license'),
    url('^privacy/', views.privacy, name='addons.privacy'),
    url('^abuse/', views.report_abuse, name='addons.abuse'),
    url('^share$', views.share, name='addons.share'),
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

    url('^purchase/$', views.purchase, name='addons.purchase'),
    url(r'purchase/start$', views.paypal_start,
        name='addons.purchase.start'),
    url('^purchase/thanks/$', views.purchase_thanks,
        name='addons.purchase.thanks'),
    url('^purchase/error/$', views.purchase_error,
        name='addons.purchase.error'),
    url('^purchase/(?P<status>cancel|complete)$',
        views.purchase_complete, name='addons.purchase.finished'),

    url('^about$', lambda r, addon_id: redirect('addons.installed',
                                                 addon_id, permanent=True),
                   name='addons.about'),

    ('^reviews/', include(review_patterns('addons'))),
    ('^statistics/', include(stats_patterns)),
    ('^versions/', include('versions.urls')),
)


urlpatterns = patterns('',
    # Promo modules for the homepage
    url('^i/promos$', views.homepage_promos, name='addons.homepage_promos'),

    # URLs for a single add-on.
    ('^addon/%s/' % ADDON_ID, include(detail_patterns)),

    # Accept extra junk at the end for a cache-busting build id.
    url('^addons/buttons.js(?:/.+)?$', 'addons.buttons.js'),

    # For happy install button debugging.
    url('^addons/smorgasbord$', 'addons.buttons.smorgasbord'),

    # Remora EULA and Privacy policy URLS
    ('^addons/policy/0/(?P<addon_id>\d+)/(?P<file_id>\d+)',
     lambda r, addon_id, file_id: redirect('addons.eula',
                                  addon_id, file_id, permanent=True)),
    ('^addons/policy/0/(?P<addon_id>\d+)/',
     lambda r, addon_id: redirect('addons.privacy',
                                  addon_id, permanent=True)),

    ('^versions/license/(\d+)$', views.license_redirect),
)
