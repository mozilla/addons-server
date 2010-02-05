from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
    url('^monitor$', views.monitor, name='amo.monitor'),
)
