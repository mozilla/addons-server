from django.conf.urls.defaults import patterns, url, include
from django.views.decorators.cache import never_cache

from . import views

services_patterns = patterns('',
    url('^paypal$', never_cache(views.paypal), name='amo.paypal'),
)

urlpatterns = patterns('',
    ('^services/', include(services_patterns)),
)
