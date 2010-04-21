from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^(?P<version>[^/]+)/(?P<os>[^/]+)$', views.pane,
        name='discovery.pane'),
)
