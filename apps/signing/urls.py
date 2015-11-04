from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^addons/(?P<guid>[^/]+)/versions/(?P<version_string>[^/]+)/$',
        views.VersionView.as_view(),
        name='signing.version'),
    # .* at the end to match filenames.
    # /file/:id/some-file.xpi
    url('^file/(?P<file_id>\d+)(?:/.*)?',
        views.SignedFile.as_view(), name='signing.file'),
]
