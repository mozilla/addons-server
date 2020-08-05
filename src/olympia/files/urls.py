from django.conf.urls import url

from olympia.files import views

# This set of URL patterns is not included under `/files/` in
# `src/olympia/urls.py`:
upload_patterns = [
    url(r'^file/(?P<uuid>[0-9a-f]{32})/', views.serve_file_upload,
        name='files.serve_file_upload'),
]
