from django.conf.urls import include, url


v3_api_urls = [
    url(r'^abuse/', include('olympia.abuse.urls')),
    url(r'^accounts/', include('olympia.accounts.urls')),
    url(r'^addons/', include('olympia.addons.api_urls')),
    url(r'^', include('olympia.discovery.api_urls')),
    url(r'^reviews/', include('olympia.ratings.api_urls')),
    url(r'^reviewers/', include('olympia.reviewers.api_urls')),
    url(r'^', include('olympia.signing.urls')),
    url(r'^activity/', include('olympia.activity.urls')),
    url(r'^github/', include('olympia.github.urls')),
]

urlpatterns = [
    url(r'^v3/', include(v3_api_urls, namespace='v3')),
    url(r'^v4/', include(v3_api_urls, namespace='v4')),
]
