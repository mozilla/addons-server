from django.conf.urls.defaults import patterns, url, include
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt

from . import views


# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
    url('^$', views.addon_detail, name='addons.detail'),
    url('^eula/(?P<file_id>\d+)?$', views.eula, name='addons.eula'),
    url('^license/(?P<version>[^/]+)?', views.license, name='addons.license'),
    url('^privacy/', views.privacy, name='addons.privacy'),
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
    url('^contribute/', views.contribute, name='addons.contribute'),
    ('^about$', lambda r, addon_id: redirect('addons.installed',
                                             addon_id, permanent=True)),

    ('^reviews/', include('reviews.urls')),
    ('^statistics/', include('stats.urls')),
    ('^versions/', include('versions.urls')),
)


urlpatterns = patterns('',
    # The homepage.
    url('^$', views.home, name='home'),

    # URLs for a single add-on.
    ('^addon/(?P<addon_id>\d+)/', include(detail_patterns)),

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
