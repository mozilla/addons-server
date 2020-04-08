from django.conf.urls import include, url
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from olympia.accounts.utils import redirect_for_login
from olympia.addons.urls import ADDON_ID

from . import views


# Hijack the admin's login to use our pages.
def login(request):
    # if the user has permission, just send them to the index page
    if request.method == 'GET' and admin.site.has_permission(request):
        next_path = request.GET.get(REDIRECT_FIELD_NAME)
        return redirect(next_path or 'admin:index')
    # otherwise, they're logged in but don't have permission return a 403.
    elif request.user.is_authenticated:
        raise PermissionDenied
    else:
        return redirect_for_login(request)


admin.site.site_header = admin.site.index_title = 'AMO Administration'
admin.site.login = login


urlpatterns = [
    # AMO stuff.
    url(r'^$', views.index, name='zadmin.index'),
    url(r'^models$', lambda r: redirect('admin:index'), name='zadmin.home'),
    url(r'^addon/manage/%s/$' % ADDON_ID,
        views.addon_manage, name='zadmin.addon_manage'),
    url(r'^addon/recalc-hash/(?P<file_id>\d+)/', views.recalc_hash,
        name='zadmin.recalc_hash'),
    url(r'^env$', views.env, name='zadmin.env'),
    url(r'^settings', views.show_settings, name='zadmin.settings'),
    url(r'^fix-disabled', views.fix_disabled_file, name='zadmin.fix-disabled'),

    url(r'^file-upload/(?P<uuid>[0-9a-f]{32})/download$',
        views.download_file_upload, name='zadmin.download_file_upload'),

    url(r'^elastic$', views.elastic, name='zadmin.elastic'),
    url(r'^addon-search$', views.addon_search, name='zadmin.addon-search'),

    # The Django admin.
    url(r'^models/',
        include((admin.site.get_urls(), 'admin'), namespace=admin.site.name)),
    url(r'^models/(?P<app_id>.+)/(?P<model_id>.+)/search\.json$',
        views.general_search, name='zadmin.search'),
]
