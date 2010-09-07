from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^$', views.index, name='devhub.index'),
    url('^addons/activity$', views.addons_activity,
        name='devhub.addons_activity'),
)
