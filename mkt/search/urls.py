from django.conf.urls.defaults import patterns, url

from search.views import ajax_search_suggestions
from . import views


urlpatterns = patterns('',
    url('^$', views.app_search, name='search.search'),
    url('^suggestions$', ajax_search_suggestions,
        name='search.suggestions'),
)
