from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns('',
    # This is only used by the featured app admin.
    url('^ajax/apps$', views.ajax_search, name='search.apps_ajax'),
)
