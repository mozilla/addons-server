from django.conf.urls.defaults import patterns, url, include
from django.shortcuts import redirect

from urlconf_decorator import decorate

from amo.decorators import write
from . import views

# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
    # Redirect to the edit page from the base.
    url('^$', lambda r: redirect('devhub.addons.edit', permanent=True)),
    url('^edit$', views.addons_edit, name='devhub.addons.edit'),
    url('^ownership$', views.addons_owner, name='devhub.addons.owner'),
)

urlpatterns = decorate(write, patterns('',
    url('^$', views.index, name='devhub.index'),

    # URLs for a single add-on.
    ('^addon/(?P<addon_id>\d+)/', include(detail_patterns)),
    # Redirect people who have /addons/ instead of /addon/.
    ('^addons/\d+/.*', lambda r: redirect(r.path.replace('addons', 'addon', 1))),

    # Redirect to /addons/ at the base.
    url('^addon$', lambda r: redirect('devhub.addons', permanent=True)),
    url('^addons$', views.addons_dashboard, name='devhub.addons'),
    url('^addons/activity$', views.addons_activity,
        name='devhub.addons.activity'),
    url('^upload$', views.upload, name='devhub.upload'),
    url('^upload/([^/]+)$', views.upload_detail,
        name='devhub.upload_detail'),
))
