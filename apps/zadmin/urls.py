from django.conf.urls import include, patterns, url
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from addons.urls import ADDON_ID
from amo.urlresolvers import reverse
from . import views


urlpatterns = patterns('',
    # AMO stuff.
    url('^$', views.index, name='zadmin.index'),
    url('^models$', lambda r: redirect('admin:index'), name='zadmin.home'),
    url('^addon/manage/%s/$' % ADDON_ID,
        views.addon_manage, name='zadmin.addon_manage'),
    url('^addon/recalc-hash/(?P<file_id>\d+)/', views.recalc_hash,
        name='zadmin.recalc_hash'),
    url('^env$', views.env, name='amo.env'),
    url('^flagged', views.flagged, name='zadmin.flagged'),
    url('^langpacks', views.langpacks, name='zadmin.langpacks'),
    url('^hera', views.hera, name='zadmin.hera'),
    url('^memcache$', views.memcache, name='zadmin.memcache'),
    url('^settings', views.show_settings, name='zadmin.settings'),
    url('^fix-disabled', views.fix_disabled_file, name='zadmin.fix-disabled'),
    url(r'^validation/application_versions\.json$',
        views.application_versions_json,
        name='zadmin.application_versions_json'),
    url(r'^validation/start$', views.start_validation,
        name='zadmin.start_validation'),
    url(r'^validation/job-status\.json$', views.job_status,
        name='zadmin.job_status'),
    url(r'^validation/set/(?P<job>\d+)$', views.notify_success,
        name='zadmin.notify.success'),
    url(r'^validation/notify/(?P<job>\d+)$', views.notify_failure,
        name='zadmin.notify.failure'),
    url(r'^validation/notify/syntax.json$', views.notify_syntax,
        name='zadmin.notify.syntax'),
    url(r'^validation/(?P<job_id>\d+)/tally\.csv$',
        views.validation_tally_csv, name='zadmin.validation_tally_csv'),
    url(r'^validation$', views.validation, name='zadmin.validation'),
    url(r'^email_preview/(?P<topic>.*)\.csv$',
        views.email_preview_csv, name='zadmin.email_preview_csv'),
    url(r'^compat$', views.compat, name='zadmin.compat'),
    url(r'^jetpack$', views.jetpack, name='zadmin.jetpack'),
    url(r'^jetpack/resend/(?P<file_id>\d+)$', views.jetpack_resend,
        name='zadmin.jetpack.resend'),

    url('^features$', views.features, name='zadmin.features'),
    url('^features/collections\.json$', views.es_collections_json,
        name='zadmin.collections_json'),
    url('^features/featured-collection$', views.featured_collection,
        name='zadmin.featured_collection'),

    url('^monthly-pick$', views.monthly_pick,
        name='zadmin.monthly_pick'),

    url('^elastic$', views.elastic, name='zadmin.elastic'),
    url('^mail$', views.mail, name='zadmin.mail'),
    url('^email-devs$', views.email_devs, name='zadmin.email_devs'),
    url('^addon-search$', views.addon_search, name='zadmin.addon-search'),
    url('^oauth-consumer-create$', views.oauth_consumer_create,
        name='zadmin.oauth-consumer-create'),
    url('^generate-error$', views.generate_error,
        name='zadmin.generate-error'),

    url('^export_email_addresses$', views.export_email_addresses,
        name='zadmin.export_email_addresses'),
    url('^email_addresses_file$', views.email_addresses_file,
        name='zadmin.email_addresses_file'),

    # Site Event admin.
    url('^events/(?P<event_id>\d+)?$', views.site_events,
        name='zadmin.site_events'),
    url('^events/(?P<event_id>\d+)/delete$', views.delete_site_event,
        name='zadmin.site_events.delete'),

    # The Django admin.
    url('^models/', include(admin.site.urls)),
    url('^models/(?P<app_id>.+)/(?P<model_id>.+)/search.json$',
        views.general_search, name='zadmin.search'),
)


# Hijack the admin's login to use our pages.
def login(request):
    # If someone is already auth'd then they're getting directed to login()
    # because they don't have sufficient permissions.
    if request.user.is_authenticated():
        raise PermissionDenied
    else:
        return redirect('%s?to=%s' % (reverse('users.login'), request.path))


admin.site.login = login
