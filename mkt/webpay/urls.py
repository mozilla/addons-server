from django.conf.urls import include, patterns, url

from rest_framework import routers
from tastypie.api import Api

from mkt.webpay.resources import (FailureNotificationView,
                                  PreparePayView, PricesViewSet,
                                  ProductIconResource, sig_check,
                                  StatusPayResource)

api = Api(api_name='webpay')
api.register(ProductIconResource())
api.register(StatusPayResource())

api_router = routers.SimpleRouter()
api_router.register(r'prices', PricesViewSet)

urlpatterns = patterns('',
    url(r'^', include(api.urls)),
    url(r'^webpay/', include(api_router.urls)),
    url(r'^webpay/prepare/', PreparePayView.as_view(), name='webpay-prepare'),
    url(r'^webpay/failure/(?P<pk>\d+)/', FailureNotificationView.as_view(),
        name='webpay-failurenotification'),
    url(r'^webpay/sig_check/$', sig_check, name='webpay-sig_check')
)
