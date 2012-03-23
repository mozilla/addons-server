from django.conf.urls.defaults import include, patterns, url

import addons.views
from . import views

urlpatterns = patterns('',
    url('^$', views.detail, name='detail'),
    url('^record$', views.record, name='detail.record'),
    url('^privacy$', views.privacy, name='detail.privacy'),

    # Submission.
    ('^purchase/', include('mkt.purchase.urls')),

    # TODO: Port abuse.
    url('^abuse$', addons.views.report_abuse, name='detail.abuse'),
)
