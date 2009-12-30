from django.conf.urls.defaults import patterns, url, include
from django.contrib import admin
from django.shortcuts import redirect


urlpatterns = patterns('',
    # AMO stuff.
    url('^$', lambda r: redirect('admin:index'), name='admin.home'),

    # The Django admin.
    url('^models/', include(admin.site.urls)),
)
