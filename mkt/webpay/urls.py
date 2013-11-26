from django.conf.urls import include, patterns, url

from rest_framework import routers

from mkt.webpay.resources import (FailureNotificationView,
                                  PreparePayView, PricesViewSet,
                                  ProductIconViewSet, sig_check,
                                  StatusPayView)


api = routers.SimpleRouter()
api.register(r'prices', PricesViewSet)
api.register(r'product/icon', ProductIconViewSet)

urlpatterns = patterns('',
    url(r'^', include(api.urls)),
    url(r'^webpay/', include(api.urls)),
    url(r'^webpay/status/(?P<uuid>[^/]+)/', StatusPayView.as_view(),
        name='webpay-status'),
    url(r'^webpay/prepare/', PreparePayView.as_view(),
        name='webpay-prepare'),
    url(r'^webpay/failure/(?P<pk>\d+)/', FailureNotificationView.as_view(),
        name='webpay-failurenotification'),
    url(r'^webpay/sig_check/$', sig_check, name='webpay-sig_check')
)
