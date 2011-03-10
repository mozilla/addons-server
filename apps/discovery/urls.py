from django.conf.urls.defaults import patterns, url, include
from django.shortcuts import redirect

from addons.urls import ADDON_ID
from . import views


# These will all start with /addon/<addon_id>/
addon_patterns = patterns('',
    url('^$', views.addon_detail, name='discovery.addons.detail'),
    url('^eula/(?P<file_id>\d+)?$', views.addon_eula,
        name='discovery.addons.eula'),
)

browser_re = '(?P<version>[^/]+)/(?P<platform>[^/]+)'

urlpatterns = patterns('',
    # Force the match so this doesn't get picked up by the wide open
    # /:version/:platform regex.
    ('^addon/%s$' % ADDON_ID,
     lambda r, addon_id: redirect('discovery.addons.detail',
                                  addon_id, permanent=True)),
    url('^addon/%s/' % ADDON_ID, include(addon_patterns)),

    url('^pane/account$', views.pane_account, name='discovery.pane_account'),
    url('^recs/%s$' % browser_re,
        views.recommendations, name='discovery.recs'),
    url('^%s$' % browser_re,
        lambda r, **kw: redirect('discovery.pane', permanent=True, **kw)),
    url('^pane/%s$' % browser_re, views.pane, name='discovery.pane'),
    url('^modules$', views.module_admin, name='discovery.module_admin'),
)
