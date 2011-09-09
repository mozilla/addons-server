from django.conf.urls.defaults import patterns, url, include
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import redirect

from devhub.views import ajax_upload_image
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
    url('^purchase/(?P<status>cancel|complete)$', views.purchase_complete,
        name='addons.purchase.finished'),

    url('^about$', lambda r, addon_id: redirect('addons.installed',
                                                 addon_id, permanent=True),
                   name='addons.about'),

    ('^reviews/', include('reviews.urls')),
    ('^statistics/', include('stats.urls')),
    ('^versions/', include('versions.urls')),
)


impala_detail_patterns = patterns('',
    ('^reviews/', include('reviews.impala_urls')),
)


urlpatterns = patterns('',
    # The homepage.
    url('^$', views.home, name='home'),
    # Promo modules for the homepage
    url('^i/promos$', views.homepage_promos, name='addons.homepage_promos'),

    # URLs for a single add-on.
    ('^addon/%s/' % ADDON_ID, include(detail_patterns)),
    # Impala deets.
    url('^i/addon/%s/' % ADDON_ID, include(impala_detail_patterns)),

    # Personas submission.
    url('^personas/submit$', views.submit_persona, name='personas.submit'),
    url('^personas/%s/submit/done$' % ADDON_ID, views.submit_persona_done,
        name='personas.submit.done'),
    url('^personas/submit/upload/'
        '(?P<upload_type>persona_header|persona_footer)$',
        ajax_upload_image, name='personas.upload_persona'),

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
