from django.conf.urls import patterns, url

from mkt.installs.api import install

urlpatterns = patterns('',
    url(r'^installs/record/', install, name='app-install-list')
)
