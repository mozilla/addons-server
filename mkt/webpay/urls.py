from django.conf.urls import include, patterns, url

from tastypie.api import Api

from mkt.webpay.resources import PriceResource


api = Api(api_name='webpay')
api.register(PriceResource())

urlpatterns = patterns('',
    url(r'^', include(api.urls)),
)
