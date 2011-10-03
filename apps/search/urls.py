from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^$', views.search, name='search.search'),
    url('^ajax$', views.ajax_search, name='search.ajax'),
    url('^suggestions$', views.ajax_search_suggestions,
        name='search.suggestions'),
    url('^es$', views.es_search, name='search.es_search'),
)
