from django.conf.urls.defaults import patterns, url, include
from django.contrib import admin
from django.shortcuts import redirect

from amo.urlresolvers import reverse
from . import views


urlpatterns = patterns('',
    # AMO stuff.
    url('^$', lambda r: redirect('admin:index'), name='zadmin.home'),
    url('^env$', views.env, name='amo.env'),
    url('^flagged', views.flagged, name='zadmin.flagged'),
    url('^hera', views.hera, name='zadmin.hera'),
    url('^settings', views.settings, name='zadmin.settings'),
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
    url(r'^validation$', views.validation, name='zadmin.validation'),
    url(r'^email_preview/(?P<topic>.*)\.csv$',
        views.email_preview_csv, name='zadmin.email_preview_csv'),
    url(r'^jetpack$', views.jetpack, name='zadmin.jetpack'),
    url('^elastic$', views.elastic, name='zadmin.elastic'),
    url('^mail$', views.mail, name='zadmin.mail'),

    # The Django admin.
    url('^models/', include(admin.site.urls)),
)


# Hijack the admin's login to use our pages.
def login(request):
    url = '%s?to=%s' % (reverse('users.login'), request.path)
    return redirect(url)


admin.site.login = login
