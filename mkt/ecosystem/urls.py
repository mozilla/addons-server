from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
    url('^$', views.landing, name='ecosystem.landing'),
    url('^tutorial/(?P<page>\w+)?$', views.tutorial,
        name='ecosystem.tutorial'),
)
