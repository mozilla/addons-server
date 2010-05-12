from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^recs$', views.recommendations, name='discovery.recs'),
    url('^(?P<version>[^/]+)/(?P<platform>[^/]+)$', views.pane,
        name='discovery.pane'),
    url('^modules$', views.module_admin, name='discovery.module_admin'),
)
