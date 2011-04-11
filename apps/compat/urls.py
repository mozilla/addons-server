from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^(?P<version>[.\w]+)?$', views.index, name='compat.index'),
    url('^(?P<version>[.\w]+)/details$', views.details, name='compat.details'),
)
