from django.conf.urls import include, url


urlpatterns = [
    url(r'^v3/abuse/', include('olympia.abuse.urls')),
    url(r'^v3/accounts/', include('olympia.accounts.urls')),
    url(r'^v3/addons/', include('olympia.addons.api_urls')),
    url(r'^v3/', include('olympia.discovery.api_urls')),
    url(r'^v3/internal/', include('olympia.internal_tools.urls')),
    url(r'^v3/reviews/', include('olympia.reviews.api_urls')),
    url(r'^v3/', include('olympia.signing.urls')),
    url(r'^v3/statistics/', include('olympia.stats.api_urls')),
    url(r'^v3/activity/', include('olympia.activity.urls')),
    url(r'^v3/github/', include('olympia.github.urls')),
]
