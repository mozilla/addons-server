from django.urls import re_path

from . import views


urlpatterns = [
    re_path(r'^$', views.appversions, name='apps.appversions'),
    re_path(r'^format:rss$', views.AppversionsFeed(), name='apps.appversions.rss'),
]
