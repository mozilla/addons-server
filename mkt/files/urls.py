from django.conf.urls import include, patterns, url

from . import views


file_patterns = patterns('',
    url(r'^$', views.browse, name='mkt.files.list'),
    url(r'^(?P<type_>fragment|file)/(?P<key>.*)$', views.browse,
        name='mkt.files.list'),
    url(r'file-redirect/(?P<key>.*)$', views.redirect,
        name='mkt.files.redirect'),
    url(r'file-serve/(?P<key>.*)$', views.serve, name='mkt.files.serve'),
    url(r'status$', views.poll, name='mkt.files.poll'),
)

compare_patterns = patterns('',
    url(r'^$', views.compare, name='mkt.files.compare'),
    url(r'(?P<type_>fragment|file)/(?P<key>.*)$', views.compare,
        name='mkt.files.compare'),
    url(r'status$', views.compare_poll, name='mkt.files.compare.poll'),
)

urlpatterns = patterns('',
    ('^browse/(?P<file_id>\d+)/', include(file_patterns)),
    ('^compare/(?P<one_id>\d+)\.{3}(?P<two_id>\d+)/',
     include(compare_patterns)),
)
