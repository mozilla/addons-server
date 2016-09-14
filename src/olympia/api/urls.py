from django.conf.urls import include, patterns, url

from rest_framework_jwt.views import verify_jwt_token


urlpatterns = patterns(
    '',
    # The token-related views are only useful for our frontend, since there
    # is no possibility to obtain a jwt token for 3rd-party apps.
    url(r'^v3/frontend-token/verify/', verify_jwt_token,
        name='frontend-token-verify'),

    url(r'^v3/accounts/', include('olympia.accounts.urls')),
    url(r'^v3/addons/', include('olympia.addons.api_urls')),
    url(r'^v3/', include('olympia.discovery.api_urls')),
    url(r'^v3/internal/', include('olympia.internal_tools.urls')),
    url(r'^v3/', include('olympia.signing.urls')),
    url(r'^v3/statistics/', include('olympia.stats.api_urls')),
    url(r'^v3/activity', include('olympia.activity.urls')),
)
