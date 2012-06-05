from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^(?P<category>[^ /]+)?$', views.browse_apps, name='browse.apps'),
    url('^(?P<theme_category>[^ /]+)?$', views.browse_themes, name='browse.themes'),
)
