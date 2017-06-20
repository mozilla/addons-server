from django.conf.urls import url
from django.views.decorators.cache import never_cache

from . import views


urlpatterns = [
    url('^paypal$', never_cache(views.paypal), name='amo.paypal'),
]
