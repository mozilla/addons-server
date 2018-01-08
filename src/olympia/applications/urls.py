from django.conf.urls import url

from . import views


urlpatterns = [
    url('^$', views.appversions, name='apps.appversions'),
    url('^format:rss$', views.AppversionsFeed(), name='apps.appversions.rss'),
]
