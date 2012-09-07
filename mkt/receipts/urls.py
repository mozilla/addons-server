from django.conf.urls import patterns, url

import waffle

import amo
from . import views

# Note: this URL is embedded in receipts, if you change the URL, make sure
# that you put a redirect in.
app_receipt_patterns = patterns('',
    url('^reissue$', views.reissue, name='purchase.reissue'),
    url('^record$',
        (views.record_anon
         if waffle.switch_is_active('anonymous-free-installs')
         else views.record),
        name='detail.record'),
)

receipt_patterns = patterns('',
    url(r'^verify/%s$' % amo.APP_SLUG, views.verify,
        name='receipt.verify'),
    url(r'^issue/%s$' % amo.APP_SLUG, views.issue,
        name='receipt.issue'),
    url(r'^check/%s$' % amo.APP_SLUG, views.check,
        name='receipt.check'),
)
