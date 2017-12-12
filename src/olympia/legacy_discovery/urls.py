from django.conf.urls import include, url
from django.urls import reverse
from django.db.transaction import non_atomic_requests
from django.shortcuts import redirect

from olympia.addons.urls import ADDON_ID

from . import views


# These will all start with /addon/<addon_id>/
addon_patterns = [
    url('^$', views.addon_detail, name='discovery.addons.detail'),
    url('^eula/(?P<file_id>\d+)?$', views.addon_eula,
        name='discovery.addons.eula'),
]

browser_re = '(?P<version>[^/]+)/(?P<platform>[^/]+)'
compat_mode_re = '(?:/(?P<compat_mode>strict|normal|ignore))?'


@non_atomic_requests
def pane_redirect(req, **kw):
    kw['compat_mode'] = views.get_compat_mode(kw.get('version'))
    return redirect(reverse('discovery.pane', kwargs=kw), permanent=False)


urlpatterns = [
    # Force the match so this doesn't get picked up by the wide open
    # /:version/:platform regex.
    url('^addon/%s$' % ADDON_ID,
        lambda r, addon_id: redirect('discovery.addons.detail',
                                     addon_id, permanent=True)),
    url('^addon/%s/' % ADDON_ID, include(addon_patterns)),

    url('^pane/account$', views.pane_account, name='discovery.pane.account'),
    url('^pane/(?P<section>featured|up-and-coming)/%s$' % (
        browser_re + compat_mode_re), views.pane_more_addons,
        name='discovery.pane.more_addons'),
    url('^%s$' % (browser_re + compat_mode_re), pane_redirect),
    url('^pane/%s$' % (browser_re + compat_mode_re), views.pane,
        name='discovery.pane'),
    url('^pane/promos/%s$' % (browser_re + compat_mode_re), views.pane_promos,
        name='discovery.pane.promos'),
    url('^modules$', views.module_admin, name='discovery.module_admin'),
]
