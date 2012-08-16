from django.conf import settings
from django.conf.urls.defaults import patterns, url

from jingo.views import direct_to_template

from amo.urlresolvers import reverse

from . import views


urlpatterns = patterns('',
    url('^$', direct_to_template, {'template': 'offline/home.html'},
        name='offline.home'),
)
