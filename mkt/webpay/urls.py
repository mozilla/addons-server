from django.conf.urls import include, patterns, url

from tastypie.api import Api

from mkt.webpay.resources import FailureNotificationResource, PriceResource


api = Api(api_name='webpay')
api.register(PriceResource())
api.register(FailureNotificationResource())


urlpatterns = patterns('',
    url(r'^', include(api.urls)),
)
