from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^ajax$', views.ajax_search, name='search.ajax'),
    url('^$', views.search, name='search.search'),
)
