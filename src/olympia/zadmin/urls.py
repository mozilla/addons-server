from django.conf.urls import include, url
from django.contrib import admin
from django.shortcuts import redirect

from . import views


urlpatterns = [
    # AMO stuff.
    url(r'^$', views.index, name='zadmin.index'),
    url(r'^models$', lambda r: redirect('admin:index'), name='zadmin.home'),
    url(r'^addon/recalc-hash/(?P<file_id>\d+)/', views.recalc_hash,
        name='zadmin.recalc_hash'),
    url(r'^fix-disabled', views.fix_disabled_file, name='zadmin.fix-disabled'),

    url(r'^file-upload/(?P<uuid>[0-9a-f]{32})/download$',
        views.download_file_upload, name='zadmin.download_file_upload'),

    # The Django admin.
    url(r'^models/',
        include((admin.site.get_urls(), 'admin'), namespace=admin.site.name)),
]
