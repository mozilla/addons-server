from django.conf.urls import include, patterns, url

from . import bluevia, views


# These URLs are attached to /services
bluevia_services_patterns = patterns('',
    url('^postback$', bluevia.postback, name='bluevia.postback'),
    url('^chargeback$', bluevia.chargeback, name='bluevia.chargeback'),
)

# These URLs get attached to the app details URLs.
app_purchase_patterns = patterns('',
    url('^$', views.purchase, name='purchase'),
    url('^preapproval$', views.preapproval,
        name='detail.purchase.preapproval'),
    url('^(?P<status>cancel|complete)$', views.purchase_done,
        name='purchase.done'),
    url('^bluevia/prepare_pay$', bluevia.prepare_pay,
        name='bluevia.prepare_pay'),
    url('^prepare/prepare_refund/(?P<uuid>[^/]+)$', bluevia.prepare_refund,
        name='bluevia.prepare_refund'),
    url('^bluevia/pay_status/(?P<contrib_uuid>[^/]+)$', bluevia.pay_status,
        name='bluevia.pay_status'),
)

urlpatterns = patterns('',
    # TODO: Port these views.
    #url('^thanks/$', views.purchase_thanks, name='purchase.thanks'),
    #url('^error/$', views.purchase_error, name='purchase.error'),

    ('', include(app_purchase_patterns)),
)
