from django.urls import include, re_path

from olympia.accounts.urls import accounts_v3, accounts_v4, auth_callback_patterns
from olympia.amo.urls import api_patterns as amo_api_patterns
from olympia.addons.api_urls import addons_v3, addons_v4
from olympia.ratings.api_urls import ratings_v3, ratings_v4


v3_api_urls = [
    re_path(r'^abuse/', include('olympia.abuse.urls')),
    re_path(r'^accounts/', include(accounts_v3)),
    re_path(r'^addons/', include(addons_v3)),
    re_path(r'^', include('olympia.discovery.api_urls')),
    re_path(r'^reviews/', include(ratings_v3.urls)),
    re_path(r'^reviewers/', include('olympia.reviewers.api_urls')),
    re_path(r'^', include('olympia.signing.urls')),
    re_path(r'^activity/', include('olympia.activity.urls')),
]

v4_api_urls = [
    re_path(r'^abuse/', include('olympia.abuse.urls')),
    re_path(r'^accounts/', include(accounts_v4)),
    re_path(r'^activity/', include('olympia.activity.urls')),
    re_path(r'^addons/', include(addons_v4)),
    re_path(r'^applications/', include('olympia.applications.api_urls')),
    re_path(r'^blocklist/', include('olympia.blocklist.urls')),
    re_path(r'^', include('olympia.discovery.api_urls')),
    re_path(r'^hero/', include('olympia.hero.urls')),
    re_path(r'^ratings/', include(ratings_v4.urls)),
    re_path(r'^reviewers/', include('olympia.reviewers.api_urls')),
    re_path(r'^', include('olympia.signing.urls')),
    re_path(r'^', include(amo_api_patterns)),
    re_path(r'^promoted/', include('olympia.promoted.api_urls')),
    re_path(r'^scanner/', include('olympia.scanners.api_urls')),
]

v5_api_urls = v4_api_urls + [
    re_path(r'^shelves/', include('olympia.shelves.urls')),
]

urlpatterns = [
    re_path(r'^auth/', include((auth_callback_patterns, 'auth'))),
    re_path(r'^v3/', include((v3_api_urls, 'v3'))),
    re_path(r'^v4/', include((v4_api_urls, 'v4'))),
    re_path(r'^v5/', include((v5_api_urls, 'v5'))),
]
