from django.urls import re_path

from olympia.addons.urls import ADDON_ID
from olympia.amo.views import frontend_view

from . import views


urlpatterns = [
    re_path(r'^$', frontend_view, name='addons.versions'),
    re_path(
        r'^(?P<version_num>[^/]+)/updateinfo/$',
        views.update_info,
        name='addons.versions.update_info',
    ),
]

download_patterns = [
    # .* at the end to match filenames.
    # /file/:id/type:attachment
    re_path(
        r'^file/(?P<file_id>\d+)(?:/type:(?P<type>\w+))?(?:/.*)?',
        views.download_file,
        name='downloads.file',
    ),
    re_path(
        r'^source/(?P<version_id>\d+)', views.download_source, name='downloads.source'
    ),
    # /latest/1865/type:xpi/platform:5
    re_path(
        r'^latest/%s/(?:type:(?P<type>\w+)/)?'
        r'(?:platform:(?P<platform>\d+)/)?.*' % ADDON_ID,
        views.download_latest,
        name='downloads.latest',
    ),
]
