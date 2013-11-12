from django.conf import settings
from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter
from tastypie.api import Api
from tastypie_services.services import (ErrorResource, SettingsResource)

from mkt.submit.api import PreviewResource, StatusViewSet, ValidationResource
from mkt.api.base import AppRouter, handle_500
from mkt.api.resources import (CarrierViewSet, CategoryViewSet,
                               error_reporter, PriceTierViewSet,
                               PriceCurrencyViewSet, RefreshManifestViewSet,
                               RegionViewSet, site_config)
from mkt.collections.views import CollectionImageViewSet, CollectionViewSet
from mkt.features.views import AppFeaturesList
from mkt.search.api import SearchResource, SuggestionsResource
from mkt.webapps.api import AppViewSet, PrivacyPolicyViewSet

api = Api(api_name='apps')
api.register(ValidationResource())
api.register(PreviewResource())
api.register(SearchResource())
api.register(SuggestionsResource())

rocketfuel = SimpleRouter()
rocketfuel.register(r'collections', CollectionViewSet,
                    base_name='collections')
subcollections = AppRouter()
subcollections.register('image', CollectionImageViewSet,
                        base_name='collection-image')

apps = SimpleRouter()
apps.register(r'category', CategoryViewSet, base_name='app-category')
apps.register(r'status', StatusViewSet, base_name='app-status')
apps.register(r'app', AppViewSet, base_name='app')

subapps = AppRouter()
subapps.register('refresh-manifest', RefreshManifestViewSet,
                 base_name='app-refresh-manifest')
subapps.register('privacy', PrivacyPolicyViewSet,
                 base_name='app-privacy-policy')

services = Api(api_name='services')
if settings.ALLOW_TASTYPIE_SERVICES:
    services.register(ErrorResource(set_handler=handle_500))
    if getattr(settings, 'CLEANSED_SETTINGS_ACCESS', False):
        services.register(SettingsResource())

svcs = SimpleRouter()
svcs.register(r'carrier', CarrierViewSet, base_name='carriers')
svcs.register(r'region', RegionViewSet, base_name='regions')
svcs.register(r'price-tier', PriceTierViewSet,
              base_name='price-tier')
svcs.register(r'price-currency', PriceCurrencyViewSet,
              base_name='price-currency')

urlpatterns = patterns('',
    url(r'^', include(api.urls)),
    url(r'^apps/', include(apps.urls)),
    url(r'^apps/app/', include(subapps.urls)),
    url(r'^apps/', include('mkt.versions.urls')),
    url(r'^apps/', include('mkt.ratings.urls')),
    url(r'^apps/features/', AppFeaturesList.as_view(),
        name='api-features-feature-list'),
    url(r'^', include(services.urls)),
    url(r'^services/', include(svcs.urls)),
    url(r'^services/config/site/', site_config, name='site-config'),
    url(r'^fireplace/report_error', error_reporter, name='error-reporter'),
    url(r'^rocketfuel/', include(rocketfuel.urls)),
    url(r'^rocketfuel/collections/', include(subcollections.urls)),
)
