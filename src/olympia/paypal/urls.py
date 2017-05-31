from django.conf.urls import include, url
from django.views.decorators.cache import never_cache

from . import views

services_patterns = [
    url('^paypal$', never_cache(views.paypal), name='amo.paypal'),
]

urlpatterns = [
    ('', include(services_patterns)),
]
