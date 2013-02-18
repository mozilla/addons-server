from django.conf.urls import patterns, url

import amo
from . import views

# Note: this URL is embedded in receipts, if you change the URL, make sure
# that you put a redirect in.
app_receipt_patterns = patterns('',
    url('^reissue$', views.reissue, name='purchase.reissue'),
    url('^record$', views.record_anon, name='detail.record'),
)

receipt_patterns = patterns('',
    url(r'^verify/%s$' % amo.ADDON_UUID, views.verify,
        name='receipt.verify'),
    url(r'^issue/%s$' % amo.APP_SLUG, views.issue,
        name='receipt.issue'),
    url(r'^check/%s$' % amo.ADDON_UUID, views.check,
        name='receipt.check'),
)
