from django.urls import re_path

from . import views


urlpatterns = [
    re_path(r'^addons/$', views.VersionView.as_view(), name='signing.version'),
    re_path(
        r'^addons/(?P<guid>[^/]+)/versions/(?P<version_string>[^/]+)/'
        r'uploads/(?P<uuid>[^/]+)/$',
        views.VersionView.as_view(),
        name='signing.version',
    ),
    re_path(
        r'^addons/(?P<guid>[^/]+)/versions/(?P<version_string>[^/]+)/$',
        views.VersionView.as_view(),
        name='signing.version',
    ),
    # .* at the end to match filenames.
    # /file/:id/some-file.xpi
    re_path(
        r'^file/(?P<file_id>\d+)(?:/.*)?',
        views.SignedFile.as_view(),
        name='signing.file',
    ),
]
