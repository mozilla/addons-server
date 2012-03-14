from django.conf.urls.defaults import patterns, url

import addons.views
from . import views

urlpatterns = patterns('',
    url('^$', views.detail, name='detail'),
    url('^abuse$', addons.views.report_abuse, name='detail.abuse'),
    url('^record$', views.record, name='detail.record'),
)
