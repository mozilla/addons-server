from django.conf import settings
from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter
from tastypie.api import Api

from mkt.abuse.urls import api_patterns as abuse_api_patterns
from mkt.account.urls import api_patterns as account_api_patterns
from mkt.api.base import AppRouter
from mkt.api.resources import (CarrierViewSet, CategoryViewSet,
                               error_reporter, ErrorViewSet, PriceTierViewSet,
                               PriceCurrencyViewSet, RefreshManifestViewSet,
                               RegionViewSet, site_config)
from mkt.collections.views import CollectionImageViewSet, CollectionViewSet
from mkt.comm.urls import api_patterns as comm_api_patterns
from mkt.developers.urls import dev_api_patterns, payments_api_patterns
from mkt.features.views import AppFeaturesList
from mkt.receipts.urls import receipt_api_patterns
from mkt.reviewers.urls import api_patterns as reviewer_api_patterns
from mkt.search.api import SearchResource, SuggestionsResource
from mkt.stats.urls import stats_api_patterns, txn_api_patterns
from mkt.submit.api import PreviewResource, StatusViewSet, ValidationViewSet
from mkt.webapps.api import AppViewSet, PrivacyPolicyViewSet

# Endpoints using tastypie.
api = Api(api_name='apps')
api.register(PreviewResource())
api.register(SearchResource())
api.register(SuggestionsResource())

# Endpoints using django-rest-framework.
rocketfuel = SimpleRouter()
rocketfuel.register(r'collections', CollectionViewSet,
                    base_name='collections')

subcollections = AppRouter()
subcollections.register('image', CollectionImageViewSet,
                        base_name='collection-image')

apps = SimpleRouter()
apps.register(r'validation', ValidationViewSet, base_name='app-validation')
apps.register(r'category', CategoryViewSet, base_name='app-category')
apps.register(r'status', StatusViewSet, base_name='app-status')
apps.register(r'app', AppViewSet, base_name='app')

subapps = AppRouter()
subapps.register('refresh-manifest', RefreshManifestViewSet,
                 base_name='app-refresh-manifest')
subapps.register('privacy', PrivacyPolicyViewSet,
                 base_name='app-privacy-policy')

services = SimpleRouter()

if settings.ENABLE_API_ERROR_SERVICE:
    services.register(r'error', ErrorViewSet, base_name='error')

services.register(r'carrier', CarrierViewSet, base_name='carriers')
services.register(r'region', RegionViewSet, base_name='regions')
services.register(r'price-tier', PriceTierViewSet,
              base_name='price-tier')
services.register(r'price-currency', PriceCurrencyViewSet,
              base_name='price-currency')

urlpatterns = patterns('',
    url('', include('mkt.fireplace.urls')),
    url(r'^', include(api.urls)),
    url(r'^apps/', include(apps.urls)),
    url(r'^apps/app/', include(subapps.urls)),
    url(r'^services/', include(services.urls)),
    url(r'^services/config/site/', site_config, name='site-config'),
    url(r'^fireplace/report_error', error_reporter, name='error-reporter'),
    url(r'^rocketfuel/', include(rocketfuel.urls)),
    url(r'^rocketfuel/collections/', include(subcollections.urls)),
    url(r'^apps/', include('mkt.versions.urls')),
    url(r'^apps/', include('mkt.ratings.urls')),
    url(r'^apps/features/', AppFeaturesList.as_view(),
        name='api-features-feature-list'),
    url('', include(abuse_api_patterns)),
    url('', include(account_api_patterns)),
    url('', include('mkt.installs.urls')),
    url('', include(reviewer_api_patterns)),
    url('', include('mkt.webpay.urls')),
    url('', include(dev_api_patterns)),
    url('', include(payments_api_patterns)),
    url('', include(receipt_api_patterns)),
    url('', include('mkt.monolith.urls')),
    url('', include(comm_api_patterns)),
    url('', include(stats_api_patterns)),
    url('', include(txn_api_patterns)),
)
