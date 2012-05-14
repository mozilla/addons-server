from django.conf.urls.defaults import patterns, url

from mkt.api.authentication import MarketplaceAuth
from mkt.api.handlers import ValidationHandler
from mkt.api.resources import MarketplaceResource


extra = {'authentication': MarketplaceAuth(two_legged=True)}
validation = MarketplaceResource(handler=ValidationHandler, **extra)

urlpatterns = patterns('',
    url(r'^apps/validation(?:/(?P<id>\w+))?$', validation,
        name='api.validation'),
)
