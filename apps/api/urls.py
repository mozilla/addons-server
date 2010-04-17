from django.conf import settings
from django.conf.urls.defaults import patterns, url, include
from django.views.decorators.cache import cache_page

from . import views


API_CACHE_TIMEOUT = getattr(settings, 'API_CACHE_TIMEOUT', 500)


# Wrap class views in a lambda call so we get an fresh instance of the class
# for thread-safety.
def cached_class_view(cls):
    inner = lambda *args, **kw: cls()(*args, **kw)
    return cache_page(API_CACHE_TIMEOUT)(inner)


# Regular expressions that we use in our urls.
type_regexp = '/(?P<addon_type>[^/]*)'
limit_regexp = '/(?P<limit>\d*)'
platform_regexp = '/(?P<platform>\w*)'
version_regexp = '/(?P<version>[^/]*)'


def build_urls(base, appendages):
    """
    Many of our urls build off each other:
    e.g.
    /search/:query
    /search/:query/:type
    .
    .
    /search/:query/:type/:limit/:platform/:version
    """
    urls = [base]
    for i in range(len(appendages)):
        urls.append(base + ''.join(appendages[:i + 1]))

    return urls


base_search_regexp = r'search/(?P<query>[^/]+)'
appendages = [type_regexp, limit_regexp, platform_regexp, version_regexp]
search_regexps = build_urls(base_search_regexp, appendages)

base_list_regexp = r'list'
appendages.insert(0, '/(?P<list_type>[^/]+)')
list_regexps = build_urls(base_list_regexp, appendages)


api_patterns = patterns('',
    # Addon_details
    url('addon/(?P<addon_id>\d+)$',
        cached_class_view(views.AddonDetailView),
        name='api.addon_detail'),)

for regexp in search_regexps:
    api_patterns += patterns('',
        url(regexp + '/?$', cached_class_view(views.SearchView),
            name='api.search'))

for regexp in list_regexps:
    api_patterns += patterns('',
            url(regexp + '/?$', cached_class_view(views.ListView),
                name='api.list'))

urlpatterns = patterns('',
    # Redirect api requests without versions
    url('^((?:addon|search|list)/.*)$', views.redirect_view),

    # Append api_version to the real api views
    url(r'^(?P<api_version>\d+|\d+.\d+)/', include(api_patterns)),

)
