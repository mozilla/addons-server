from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^apps/(?P<category>[^ /]+)?$', views.categories_apps,
        name='browse.apps'),
)
