from django.conf.urls.defaults import patterns, include, url

from files import views

file_patterns = patterns('',
    url(r'^$', views.files_list, name='files.list'),
    url(r'file/(?P<key>.*)$', views.files_list, name='files.list'),
    url(r'status$', views.files_poll, name='files.poll'),
)

compare_patterns = patterns('',
    url(r'^$', views.files_compare, name='files.compare'),
    url(r'file/(?P<key>.*)$', views.files_compare, name='files.compare'),
    url(r'status$', views.files_compare_poll, name='files.compare.poll'),
)

# All URLs under /editors/
urlpatterns = patterns('',
    ('^browse/(?P<file_id>\d+)/', include(file_patterns)),
    ('^compare/(?P<one_id>\d+)\.{3}(?P<two_id>\d+)/',
     include(compare_patterns)),
)
