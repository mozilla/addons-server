from django.conf.urls import include, url

from olympia.ratings.api_urls import ratings_v3, ratings_v4


v3_api_urls = [
    url(r'^abuse/', include('olympia.abuse.urls')),
    url(r'^accounts/', include('olympia.accounts.urls')),
    url(r'^addons/', include('olympia.addons.api_urls')),
    url(r'^', include('olympia.discovery.api_urls')),
    url(r'^reviews/', include(ratings_v3.urls)),
    url(r'^reviewers/', include('olympia.reviewers.api_urls')),
    url(r'^', include('olympia.signing.urls')),
    url(r'^activity/', include('olympia.activity.urls')),
    url(r'^github/', include('olympia.github.urls')),
]

v4_api_urls = [
    url(r'^abuse/', include('olympia.abuse.urls')),
    url(r'^accounts/', include('olympia.accounts.urls')),
    url(r'^addons/', include('olympia.addons.api_urls')),
    url(r'^', include('olympia.discovery.api_urls')),
    url(r'^ratings/', include(ratings_v4.urls)),
    url(r'^reviewers/', include('olympia.reviewers.api_urls')),
    url(r'^', include('olympia.signing.urls')),
    url(r'^activity/', include('olympia.activity.urls')),
    url(r'^github/', include('olympia.github.urls')),
]

urlpatterns = [
    url(r'^v3/', include(v3_api_urls, namespace='v3')),
    url(r'^v4/', include(v4_api_urls, namespace='v4')),
]
