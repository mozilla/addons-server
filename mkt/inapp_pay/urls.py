from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url(r'^pay_start$', views.pay_start, name='inapp_pay.pay_start'),
    url(r'^pay$', views.pay, name='inapp_pay.pay'),
    url(r'^(?P<config_pk>[^/]+)/(?P<status>cancel|complete)$', views.pay_done,
        name='inapp_pay.pay_done'),
)
