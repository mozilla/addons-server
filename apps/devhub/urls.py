from django.conf.urls.defaults import patterns, url, include
from django.shortcuts import redirect

from urlconf_decorator import decorate

from amo.decorators import write
from . import views

# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
    # Redirect to the edit page from the base.
    url('^$', lambda r, addon_id: redirect('devhub.addons.edit', addon_id,
                                           permanent=True)),
    url('^edit$', views.edit, name='devhub.addons.edit'),
    url('^ownership$', views.ownership, name='devhub.addons.owner'),
    url('^payments$', views.payments, name='devhub.addons.payments'),
    url('^payments/disable$', views.disable_payments,
        name='devhub.addons.payments.disable'),
    url('^profile$', views.profile, name='devhub.addons.profile'),
    url('^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section, name='devhub.addons.section'),

    url('^versions/$', views.version_list, name='devhub.versions'),
    url('^versions/(?P<version_id>\d+)$', views.version_edit,
        name='devhub.versions.edit'),
    url('^versions/(?P<version>[^/]+)$', views.version_bounce),

    url('^submit-finished$',
        views.submit_finished, name='devhub.submit.finished'),
)

urlpatterns = decorate(write, patterns('',
    url('^$', views.index, name='devhub.index'),

    # URLs for a single add-on.
    ('^addon/(?P<addon_id>\d+)/', include(detail_patterns)),
    # Redirect people who have /addons/ instead of /addon/.
    ('^addons/\d+/.*',
     lambda r: redirect(r.path.replace('addons', 'addon', 1))),

    # Add-on submission
    url('^addon/submit$', views.submit, name='devhub.submit'),

    # Redirect to /addons/ at the base.
    url('^addon$', lambda r: redirect('devhub.addons', permanent=True)),
    url('^addons$', views.dashboard, name='devhub.addons'),
    url('^addons/activity$', views.activity,
        name='devhub.addons.activity'),
    url('^upload$', views.upload, name='devhub.upload'),
    url('^upload/([^/]+)$', views.upload_detail,
        name='devhub.upload_detail')))
