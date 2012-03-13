from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
    url('^$', views.detail, name='detail'),
    url('^record$', views.record, name='detail.record'),
)
