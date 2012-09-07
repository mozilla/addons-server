from django.conf.urls import include, patterns, url
from django.views.decorators.cache import never_cache

from . import views

services_patterns = patterns('',
    url('^paypal$', never_cache(views.paypal), name='amo.paypal'),
)

urlpatterns = patterns('',
    ('', include(services_patterns)),
)
