from django.conf.urls import include, patterns, url
from django.db.transaction import non_atomic_requests

from rest_framework_jwt.views import refresh_jwt_token, verify_jwt_token

from olympia.addons.urls import ADDON_ID
from olympia.api import views


# Wrap class views in a lambda call so we get an fresh instance of the class
# for thread-safety.
@non_atomic_requests
def api_view(cls):
    return lambda *args, **kw: cls()(*args, **kw)


# Regular expressions that we use in our urls.
type_regexp = '/(?P<addon_type>[^/]*)'
limit_regexp = '/(?P<limit>\d*)'
platform_regexp = '/(?P<platform>\w*)'
version_regexp = '/(?P<version>[^/]*)'
compat_mode = '(?:/(?P<compat_mode>(?:strict|normal|ignore)))?'


def build_urls(base, appendages):
    """
    Many of our urls build off each other:
    e.g.
    /search/:query
    /search/:query/:type
    .
    .
    /search/:query/:type/:limit/:platform/:version
    /search/:query/:type/:limit/:platform/:version/:compatMode
    """
    urls = [base]
    for i in range(len(appendages)):
        urls.append(base + ''.join(appendages[:i + 1]))

    return urls


base_search_regexp = r'search/(?P<query>[^/]+)'
appendages = [type_regexp, limit_regexp, platform_regexp, version_regexp,
              compat_mode]
search_regexps = build_urls(base_search_regexp, appendages)

base_list_regexp = r'list'
appendages.insert(0, '/(?P<list_type>[^/]+)')
list_regexps = build_urls(base_list_regexp, appendages)

api_patterns = patterns(
    '',
    # Addon_details
    url('addon/%s$' % ADDON_ID, api_view(views.AddonDetailView),
        name='api.addon_detail'),
    url(r'^get_language_packs$', api_view(views.LanguageView),
        name='api.language'),)

for regexp in search_regexps:
    api_patterns += patterns(
        '',
        url(regexp + '/?$', api_view(views.SearchView), name='api.search'))

for regexp in list_regexps:
    api_patterns += patterns(
        '',
        url(regexp + '/?$', api_view(views.ListView), name='api.list'))

urlpatterns = patterns(
    '',
    # Redirect api requests without versions
    url('^((?:addon|search|list)/.*)$', views.redirect_view),

    # Legacy API.
    url(r'^1.5/search_suggestions/', views.search_suggestions),
    url(r'^(?P<api_version>\d+|\d+.\d+)/search/guid:(?P<guids>.*)',
        views.guid_search),
    url(r'^(?P<api_version>\d+|\d+.\d+)/', include(api_patterns)),

    # Newer APIs.
    # Those token-related views are only useful for our frontend, since there
    # is no possibility to obtain a jwt token for 3rd-party apps.
    url(r'^v3/frontend-token/verify/', verify_jwt_token,
        name='frontend-token-verify'),
    url(r'^v3/frontend-token/refresh/', refresh_jwt_token,
        name='frontend-token-refresh'),

    url(r'^v3/accounts/', include('olympia.accounts.urls')),
    url(r'^v3/addons/', include('olympia.addons.api_urls')),
    url(r'^v3/', include('olympia.signing.urls')),
    url(r'^v3/statistics/', include('olympia.stats.api_urls')),
)
