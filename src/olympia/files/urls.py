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
    url(r'^uploads/(?P<uuid>[0-9a-f]{32})/', views.serve_file_upload,
        name='files.serve_file_upload'),
]
