from django.conf import settings
from django.urls import include, re_path

from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

from olympia.accounts.urls import accounts_v3, accounts_v4, auth_urls
from olympia.addons.api_urls import addons_v3, addons_v4, addons_v5
from olympia.amo.urls import api_patterns as amo_api_patterns
from olympia.ratings.api_urls import ratings_v3, ratings_v4


def get_versioned_api_routes(version, url_patterns):
    route_pattern = r'^{}/'.format(version)

    schema_view = get_schema_view(
        openapi.Info(
            title='AMO API',
            default_version=version,
            description='The official API for addons.mozilla.org.',
        ),
        public=True,
        permission_classes=(permissions.AllowAny,),
    )

    routes = url_patterns

    # For now, this feature is only enabled in dev mode
    if settings.DEV_MODE:
        routes.extend(
            [
                re_path(
                    r'^swagger(?P<format>\.json|\.yaml)$',
                    schema_view.without_ui(cache_timeout=0),
                    name='schema-json',
                ),
                re_path(
                    r'^swagger/$',
                    schema_view.with_ui('swagger', cache_timeout=0),
                    name='schema-swagger-ui',
                ),
                re_path(
                    r'^redoc/$',
                    schema_view.with_ui('redoc', cache_timeout=0),
                    name='schema-redoc',
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
