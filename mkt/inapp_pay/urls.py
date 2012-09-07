from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns('',
    url(r'^lobby$', views.lobby, name='inapp_pay.lobby'),
    url(r'^pay_start$', views.pay_start, name='inapp_pay.pay_start'),
    url(r'^pay$', views.pay, name='inapp_pay.pay'),
    url(r'^preauth$', views.preauth,
        name='inapp_pay.preauth'),
    url(r'^(?P<config_pk>[^/]+)/(?P<status>cancel|complete)$',
        views.pay_status, name='inapp_pay.pay_status'),
)
