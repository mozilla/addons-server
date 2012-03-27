from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^pay_start$', views.pay_start, name='inapp_pay.pay_start'),
    url('^pay$', views.pay, name='inapp_pay.pay'),
)
