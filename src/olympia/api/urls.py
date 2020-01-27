from django.conf.urls import include, url

from olympia.accounts.urls import (
    accounts_v3, accounts_v4, auth_callback_patterns)
from olympia.amo.urls import api_patterns as amo_api_patterns
from olympia.addons.api_urls import addons_v3, addons_v4
from olympia.ratings.api_urls import ratings_v3, ratings_v4


v3_api_urls = [
    url(r'^abuse/', include('olympia.abuse.urls')),
    url(r'^accounts/', include(accounts_v3)),
    url(r'^addons/', include(addons_v3)),
    url(r'^', include('olympia.discovery.api_urls')),
    url(r'^reviews/', include(ratings_v3.urls)),
    url(r'^reviewers/', include('olympia.reviewers.api_urls')),
    url(r'^', include('olympia.signing.urls')),
    url(r'^activity/', include('olympia.activity.urls')),
]

v4_api_urls = [
    url(r'^abuse/', include('olympia.abuse.urls')),
    url(r'^accounts/', include(accounts_v4)),
    url(r'^activity/', include('olympia.activity.urls')),
    url(r'^addons/', include(addons_v4)),
    url(r'^', include('olympia.discovery.api_urls')),
    url(r'^ratings/', include(ratings_v4.urls)),
    url(r'^reviewers/', include('olympia.reviewers.api_urls')),
    url(r'^', include('olympia.signing.urls')),
    url(r'^', include(amo_api_patterns)),
    url(r'^hero/', include('olympia.hero.urls')),
    url(r'^scanner/', include('olympia.scanners.api_urls')),
]

urlpatterns = [
    url(r'^auth/', include((auth_callback_patterns, 'auth'))),
    url(r'^v3/', include((v3_api_urls, 'v3'))),
    url(r'^v4/', include((v4_api_urls, 'v4'))),
    url(r'^v5/', include((v4_api_urls, 'v5'))),
]
