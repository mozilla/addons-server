from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
    url('^$', views.appversions, name='apps.versions'),
    url('^format:rss$', views.AppversionsFeed(), name='apps.versions.rss'),
)
