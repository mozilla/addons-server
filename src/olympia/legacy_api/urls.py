from django.conf.urls import include, url
from django.db.transaction import non_atomic_requests

from olympia.addons.urls import ADDON_ID
from olympia.legacy_api import views


# Wrap class views in a lambda call so we get an fresh instance of the class
# for thread-safety.
@non_atomic_requests
def api_view(cls):
    return lambda *args, **kw: cls()(*args, **kw)


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
appendages = [
    # Regular expressions that we use in our urls.
    r'/(?P<addon_type>[^/]*)',
    r'/(?P<limit>\d*)',
    r'/(?P<platform>\w*)',
    r'/(?P<version>[^/]*)',
    r'(?:/(?P<compat_mode>(?:strict|normal|ignore)))?',
]
search_regexps = build_urls(base_search_regexp, appendages)

appendages.insert(0, r'/(?P<list_type>[^/]+)')
list_regexps = build_urls(r'list', appendages)

legacy_api_patterns = [
    # Addon_details
    url(r'addon/%s$' % ADDON_ID, api_view(views.AddonDetailView),
        name='legacy_api.addon_detail'),
    url(r'^get_language_packs$', api_view(views.LanguageView),
        name='legacy_api.language'),
]

for regexp in search_regexps:
    legacy_api_patterns.append(
        url(regexp + r'/?$', api_view(views.SearchView),
            name='legacy_api.search'))

for regexp in list_regexps:
    legacy_api_patterns.append(
        url(regexp + r'/?$', api_view(views.ListView),
            name='legacy_api.list'))

urlpatterns = [
    # Redirect api requests without versions
    url(r'^((?:addon|search|list)/.*)$', views.redirect_view),

    # Endpoints.
    url(r'^1.5/search_suggestions/', views.search_suggestions),
    url(r'^(?P<api_version>\d+|\d+.\d+)/search/guid:(?P<guids>.*)',
        views.guid_search),
    url(r'^(?P<api_version>\d+|\d+.\d+)/', include(legacy_api_patterns)),
]
