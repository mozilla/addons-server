from django.conf.urls import include, url

from olympia.files import views


file_patterns = [
    url(r'^$', views.browse, name='files.list'),
    url(r'^(?P<type>fragment|file)/(?P<key>.*)$', views.browse,
        name='files.list'),
    url(r'file-redirect/(?P<key>.*)$', views.redirect,
        name='files.redirect'),
    url(r'file-serve/(?P<key>.*)$', views.serve, name='files.serve'),
    url(r'status$', views.poll, name='files.poll'),
]

compare_patterns = [
    url(r'^$', views.compare, name='files.compare'),
    url(r'(?P<type>fragment|file)/(?P<key>.*)$', views.compare,
        name='files.compare'),
    url(r'status$', views.compare_poll, name='files.compare.poll'),
]

urlpatterns = [
    url(r'^browse/(?P<file_id>\d+)/', include(file_patterns)),
    url(r'^compare/(?P<one_id>\d+)\.{3}(?P<two_id>\d+)/',
        include(compare_patterns)),
    url(r'^browse-redirect/(?P<version_id>\d+)/', views.browse_redirect,
        name='files.browse_redirect'),
    url(r'^compare-redirect/(?P<base_id>\d+)\.{3}(?P<head_id>\d+)/',
        views.compare_redirect, name='files.compare_redirect'),
]

# This set of URL patterns is not included under `/files/` in
# `src/olympia/urls.py`:
upload_patterns = [
    url(r'^file/(?P<uuid>[0-9a-f]{32})/', views.serve_file_upload,
        name='files.serve_file_upload'),
]
