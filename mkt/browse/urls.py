from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns('',
    url('^(?P<category>[^ /]+)?$', views.browse_apps, name='browse.apps'),
)
