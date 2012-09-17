from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns('',
    url('^home$', views.home, name='offline.home'),
)
