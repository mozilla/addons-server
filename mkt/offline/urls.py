from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns('',
    url('^home$', views.home, name='offline.home'),
    url('^stub$', views.stub, name='offline.stub'),
)
