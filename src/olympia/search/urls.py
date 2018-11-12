from django.conf.urls import url

from . import views


urlpatterns = [
    url(r'^(?:es)?$', views.search, name='search.search'),
    url(r'^ajax$', views.ajax_search, name='search.ajax'),
    url(r'^suggestions$', views.ajax_search_suggestions,
        name='search.suggestions'),
]
