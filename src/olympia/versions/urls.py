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
    # /file/<id>/type:attachment/lol.xpi - everything after the file id is
    # ignored though.
    re_path(
        (
            r'^file/(?P<file_id>\d+)/'
            r'(?:type:(?P<download_type>\w+)/)?(?:(?P<filename>[\w+.-]*))?$'
        ),
        views.download_file,
        name='downloads.file',
    ),
    re_path(
        r'^source/(?P<version_id>\d+)', views.download_source, name='downloads.source'
    ),
    # /latest/<id>/type:xpi/platform:5/lol.xpi - everything after the addon id
    # is ignored though.
    re_path(
        (
            r'^latest/%s/'
            r'(?:type:(?P<download_type>\w+)/)?'
            r'(?:platform:(?P<platform>\d+)/)?'
            r'(?:(?P<filename>[\w+.-]*))?$'
        )
        % ADDON_ID,
        views.download_latest,
        name='downloads.latest',
    ),
]
