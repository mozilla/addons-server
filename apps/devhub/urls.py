from django.conf.urls.defaults import patterns, url, include
from django.shortcuts import redirect

from urlconf_decorator import decorate

from amo.decorators import write
from . import views


# These will all start with /addon/<addon_id>/submit/
submit_patterns = patterns('',
    url('^$', lambda r, addon_id: redirect('devhub.submit.7', addon_id)),
    url('^3$', views.submit_describe, name='devhub.submit.3'),
    url('^4$', views.submit_media, name='devhub.submit.4'),
    url('^5$', views.submit_license, name='devhub.submit.5'),
    url('^6$', views.submit_select_review, name='devhub.submit.6'),
    url('^7$', views.submit_done, name='devhub.submit.7'),
    url('^bump$', views.submit_bump, name='devhub.submit.bump'),
)

# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
    # Redirect to the edit page from the base.
    url('^$', lambda r, addon_id: redirect('devhub.addons.edit', addon_id,
                                           permanent=True)),
    url('^edit$', views.edit, name='devhub.addons.edit'),
    url('^delete$', views.delete, name='devhub.addons.delete'),
    url('^disable$', views.disable, name='devhub.addons.disable'),
    url('^enable$', views.enable, name='devhub.addons.enable'),
    url('^cancel$', views.cancel, name='devhub.addons.cancel'),
    url('^ownership$', views.ownership, name='devhub.addons.owner'),
    url('^payments$', views.payments, name='devhub.addons.payments'),
    url('^payments/disable$', views.disable_payments,
        name='devhub.addons.payments.disable'),
    url('^profile$', views.profile, name='devhub.addons.profile'),
    url('^profile/remove$', views.remove_profile,
        name='devhub.addons.profile.remove'),
    url('^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section, name='devhub.addons.section'),
    url('^icon_upload$',
        views.addons_icon_upload, name='devhub.addons.icon_upload'),

    url('^versions/$', views.version_list, name='devhub.versions'),
    url('^versions/delete$', views.version_delete,
        name='devhub.versions.delete'),
    url('^versions/add$', views.version_add, name='devhub.versions.add'),
    url('^versions/(?P<version_id>\d+)$', views.version_edit,
        name='devhub.versions.edit'),
    url('^versions/(?P<version_id>\d+)/add$', views.version_add_file,
        name='devhub.versions.add_file'),
    url('^versions/(?P<version>[^/]+)$', views.version_bounce),

    url('^submit/', include(submit_patterns)),
    url('^submit/resume$', views.submit_resume, name='devhub.submit.resume'),
)

# These will all start with /ajax/addon/<addon_id>/
ajax_patterns = patterns('',
    url('^versions/compatibility/status$',
        views.ajax_compat_status, name='devhub.ajax.compat.status'),
    url('^versions/compatibility/error$',
        views.ajax_compat_error, name='devhub.ajax.compat.error'),
    url('^versions/(?P<version_id>\d+)/compatibility$',
        views.ajax_compat_update, name='devhub.ajax.compat.update'),
)

urlpatterns = decorate(write, patterns('',
    url('^$', views.index, name='devhub.index'),

    # URLs for a single add-on.
    ('^addon/(?P<addon_id>\d+)/', include(detail_patterns)),
    ('^ajax/addon/(?P<addon_id>\d+)/', include(ajax_patterns)),

    # Redirect people who have /addons/ instead of /addon/.
    ('^addons/\d+/.*',
     lambda r: redirect(r.path.replace('addons', 'addon', 1))),

    # Add-on submission
    url('^addon/submit/$',
        lambda r: redirect('devhub.submit.1', permanent=True)),
    url('^addon/submit/1$', views.submit, name='devhub.submit.1'),
    url('^addon/submit/2$', views.submit_addon,
        name='devhub.submit.2'),

    # Redirect to /addons/ at the base.
    url('^addon$', lambda r: redirect('devhub.addons', permanent=True)),
    url('^addons$', views.dashboard, name='devhub.addons'),
    url('^feed$', views.feed, name='devhub.feed_all'),
    url('^feed/(?P<addon_id>\d+)$', views.feed, name='devhub.feed'),
    url('^upload$', views.upload, name='devhub.upload'),
    url('^upload/([^/]+)(?:/([^/]+))?$', views.upload_detail,
        name='devhub.upload_detail')),
)
