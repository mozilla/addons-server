from django.conf.urls.defaults import patterns, url

import addons.views
from . import views

urlpatterns = patterns('',
    url('^$', views.detail, name='detail'),
    url('^record$', views.record, name='detail.record'),

    # TODO: Port abuse.
    url('^abuse$', addons.views.report_abuse, name='detail.abuse'),
)
