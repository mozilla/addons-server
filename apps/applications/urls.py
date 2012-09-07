from django.conf.urls import patterns, url

from . import views

urlpatterns = patterns('',
    url('^$', views.appversions, name='apps.appversions'),
    url('^format:rss$', views.AppversionsFeed(), name='apps.appversions.rss'),
)
