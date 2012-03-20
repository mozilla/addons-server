from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^pay_start$', views.pay_start, name='payments.pay_start'),
    url('^pay$', views.pay, name='payments.pay'),
)
