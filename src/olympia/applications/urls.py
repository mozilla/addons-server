from django.conf.urls import url

from . import views


urlpatterns = [
    url(r'^$', views.appversions, name='apps.appversions'),
    url(r'^format:rss$', views.AppversionsFeed(), name='apps.appversions.rss'),
]
