from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import include, re_path

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerSplitView,
)

from olympia.accounts.urls import accounts_v3, accounts_v4, auth_urls
from olympia.addons.api_urls import addons_v3, addons_v4, addons_v5
from olympia.amo.urls import api_patterns as amo_api_patterns
from olympia.ratings.api_urls import ratings_v3, ratings_v4


def get_versioned_api_routes(version, url_patterns):
    route_pattern = r'^{}/'.format(version)
    url_name = 'schema'

    routes = url_patterns

    try:
        static_swagger_ui_js = staticfiles_storage.url(f'js/swagger/{version}.js')
    except ValueError:
        static_swagger_ui_js = None

    # We always include the schema endpoint in the API routes.
    # The build depends on being able to generate swagger assets
    # that in turn depend on a resolvable schema endpoint.
    routes.append(
        re_path(
            r'^schema/$',
            SpectacularAPIView.as_view(),
            name=url_name,
        ),
    )

    # Only include the UI routes if the feature flag is enabled.
    if settings.SWAGGER_UI_ENABLED:
        routes.extend(
            [
                re_path(
                    r'^swagger/$',
                    SpectacularSwaggerSplitView.as_view(
                        url_name=url_name,
                        url_self=static_swagger_ui_js,
                    ),
                    name=f'{url_name}-swagger',
                ),
                re_path(
                    r'^redoc/$',
                    SpectacularRedocView.as_view(url_name=url_name),
                    name=f'{url_name}-redoc',
                ),
            ]
        )

    return (re_path(route_pattern, include((routes, version))),)


v3_api_urls = [
    re_path(r'^abuse/', include('olympia.abuse.api_urls')),
    re_path(r'^accounts/', include(accounts_v3)),
    re_path(r'^addons/', include(addons_v3)),
    re_path(r'^', include('olympia.discovery.api_urls')),
    re_path(r'^reviews/', include(ratings_v3.urls)),
    re_path(r'^reviewers/', include('olympia.reviewers.api_urls')),
    re_path(r'^', include('olympia.signing.urls')),
    re_path(r'^activity/', include('olympia.activity.api_urls')),
]

v4_api_urls = [
    re_path(r'^abuse/', include('olympia.abuse.api_urls')),
    re_path(r'^accounts/', include(accounts_v4)),
    re_path(r'^activity/', include('olympia.activity.api_urls')),
    re_path(r'^addons/', include(addons_v4)),
    re_path(r'^applications/', include('olympia.applications.api_urls')),
    re_path(r'^blocklist/', include('olympia.blocklist.urls')),
    re_path(r'^', include('olympia.discovery.api_urls')),
    re_path(r'^hero/', include('olympia.hero.urls')),
    re_path(r'^ratings/', include(ratings_v4.urls)),
    re_path(r'^reviewers/', include('olympia.reviewers.api_urls')),
    re_path(r'^', include('olympia.signing.urls')),
    re_path(r'^', include(amo_api_patterns)),
    re_path(r'^scanner/', include('olympia.scanners.api_urls')),
]

v5_api_urls = [
    re_path(r'^abuse/', include('olympia.abuse.api_urls')),
    re_path(r'^accounts/', include(accounts_v4)),
    re_path(r'^activity/', include('olympia.activity.api_urls')),
    re_path(r'^addons/', include(addons_v5)),
    re_path(r'^applications/', include('olympia.applications.api_urls')),
    re_path(r'^blocklist/', include('olympia.blocklist.urls')),
    re_path(r'^', include('olympia.discovery.api_urls')),
    re_path(r'^hero/', include('olympia.hero.urls')),
    re_path(r'^ratings/', include(ratings_v4.urls)),
    re_path(r'^reviewers/', include('olympia.reviewers.api_urls')),
    re_path(r'^', include(amo_api_patterns)),
    re_path(r'^scanner/', include('olympia.scanners.api_urls')),
    re_path(r'^shelves/', include('olympia.shelves.urls')),
]


urlpatterns = [
    re_path(r'^auth/', include((auth_urls, 'auth'))),
    *get_versioned_api_routes('v3', v3_api_urls),
    *get_versioned_api_routes('v4', v4_api_urls),
    *get_versioned_api_routes('v5', v5_api_urls),
]
