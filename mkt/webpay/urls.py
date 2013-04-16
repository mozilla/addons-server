from django.conf.urls import include, patterns, url

from tastypie.api import Api

from mkt.webpay.resources import (FailureNotificationResource, PriceResource,
                                  ProductIconResource)


api = Api(api_name='webpay')
api.register(FailureNotificationResource())
api.register(PriceResource())
api.register(ProductIconResource())


urlpatterns = patterns('',
    url(r'^', include(api.urls)),
)
