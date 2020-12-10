from django.urls import include, re_path
from django.contrib import admin
from django.shortcuts import redirect

from . import views


urlpatterns = [
    # AMO stuff.
    re_path(r'^$', lambda r: redirect('admin:index')),
    re_path(
        r'^addon/recalc-hash/(?P<file_id>\d+)/',
        views.recalc_hash,
        name='zadmin.recalc_hash',
    ),
    # The Django admin.
    re_path(
        r'^models/',
        include((admin.site.get_urls(), 'admin'), namespace=admin.site.name),
    ),
]
