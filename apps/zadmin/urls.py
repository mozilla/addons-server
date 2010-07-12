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

    # The Django admin.
    url('^models/', include(admin.site.urls)),
)


# Hijack the admin's login to use our pages.
def login(request):
    url = '%s?to=%s' % (reverse('users.login'), request.path)
    return redirect(url)


admin.site.login = login
