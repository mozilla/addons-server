from django.conf.urls import patterns, url

from . import views

urlpatterns = patterns('',
    url('^$', views.landing, name='ecosystem.landing'),
    url('^installation$', views.installation, name='ecosystem.installation'),
    url('^support$', views.support, name='ecosystem.support'),
    url('^docs/(?P<page>\w+)?$', views.documentation,
        name='ecosystem.documentation'),
)
