from django.conf.urls import include, patterns, url

from . import webpay


# These URLs are attached to /services
webpay_services_patterns = patterns('',
    url('^postback$', webpay.postback, name='webpay.postback'),
    url('^chargeback$', webpay.chargeback, name='webpay.chargeback'),
)


# These URLs get attached to the app details URLs.
app_purchase_patterns = patterns('',
    url('^webpay/prepare_pay$', webpay.prepare_pay,
        name='webpay.prepare_pay'),
    url('^webpay/pay_status/(?P<contrib_uuid>[^/]+)$', webpay.pay_status,
        name='webpay.pay_status'),
)


urlpatterns = patterns('',
    # TODO: Port these views.
    #url('^thanks/$', views.purchase_thanks, name='purchase.thanks'),
    #url('^error/$', views.purchase_error, name='purchase.error'),

    ('', include(app_purchase_patterns)),
)
