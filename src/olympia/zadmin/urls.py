from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, re_path


urlpatterns = [
    # AMO stuff.
    re_path(r'^$', lambda r: redirect('admin:index')),
    # The Django admin.
    re_path(
        r'^models/',
        include((admin.site.get_urls(), 'admin'), namespace=admin.site.name),
    ),
]
