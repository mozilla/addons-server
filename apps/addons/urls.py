from django.conf.urls.defaults import patterns, url, include
from django.shortcuts import redirect

from . import views


# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
    url('^$', views.addon_detail, name='addons.detail'),
    url('^eula/(?P<file_id>\d+)$', views.eula, name='addons.eula'),
    url('^developers(?:/(?P<extra>.+))?$', views.meet_the_developer,
        name='addons.meet'),
    url('^contribute/installed/', views.contribute_installed, name='contribute.installed'),
    
    ('^about$',
     lambda r, addon_id: redirect('contribute.installed', addon_id, permanent=True)),

    ('^reviews/', include('reviews.urls')),
    ('^statistics/', include('stats.urls')),
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
)
