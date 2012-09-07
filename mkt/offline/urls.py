from django.conf.urls import patterns, url

from jingo.views import direct_to_template


urlpatterns = patterns('',
    url('^$', direct_to_template, {'template': 'offline/home.html'},
        name='offline.home'),
)
