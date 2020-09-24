from django.conf.urls import include, url
from django.contrib import admin
from django.shortcuts import redirect

from . import views


urlpatterns = [
    # AMO stuff.
    url(r'^$', lambda r: redirect('admin:index')),
    url(r'^addon/recalc-hash/(?P<file_id>\d+)/', views.recalc_hash,
        name='zadmin.recalc_hash'),

    # The Django admin.
    url(r'^models/',
        include((admin.site.get_urls(), 'admin'), namespace=admin.site.name)),
]
