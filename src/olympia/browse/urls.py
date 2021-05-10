from django.urls import re_path

from olympia.amo.views import frontend_view


urlpatterns = [
    re_path(
        r'^language-tools/(?P<category>[^/]+)?$',
        frontend_view,
        name='browse.language-tools',
    ),
    re_path(
        r'^themes/(?:category/(?P<category>[^/]+)/)?$',
        frontend_view,
        name='browse.themes',
    ),
    re_path(
        r'^extensions/(?:category/(?P<category>[^/]+)/)?$',
        frontend_view,
        name='browse.extensions',
    ),
    re_path(
        r'^search-tools/(?P<category>[^/]+)?$',
        frontend_view,
        name='browse.search-tools',
    ),
]
