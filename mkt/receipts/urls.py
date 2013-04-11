from django.conf.urls import include, patterns, url

from tastypie.api import Api

import amo
from . import api, views

receipt = Api(api_name='receipts')
receipt.register(api.ReceiptResource())

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

receipt_api_patterns = patterns('',
    url(r'^', include(receipt.urls)),
)

test_patterns = patterns('',
    url('^$', views.devhub_install,
        name='receipt.test.install'),
    url('^issue/$', views.devhub_receipt,
        name='receipt.test.issue'),
    url('^details/$', views.devhub_details,
        name='receipt.test.details'),
    url('^verify/(?P<status>ok|expired|invalid|refunded)/$',
        views.devhub_verify,
        name='receipt.test.verify'),
)
