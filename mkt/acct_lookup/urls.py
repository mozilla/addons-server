from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^$', views.home, name='acct_lookup.home'),
)
