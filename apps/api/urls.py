from django.conf.urls.defaults import patterns, url, include

from . import views


# Wrap class views in a lambda call so we get an instance of the class for view
# so we can be thread-safe.  Yes, this lambda function returns a lambda
# function.
class_view = lambda x: lambda *args, **kwargs: x()(*args, **kwargs)

# These ultimately build up to match
# /search/:type/:limit/:platform/:version
base_search_regexp = r'search/(?P<query>[^/]+)'
search_type_regexp = base_search_regexp + '/(?P<type>[^/]*)'
search_type_limit_regexp = search_type_regexp + '/(?P<limit>\d*)'
search_type_limit_platform_regexp = (
        search_type_limit_regexp + '/(?P<platform>\w*)')
search_type_limit_platform_version_regexp = (
        search_type_limit_platform_regexp + '/(?P<version>[^/]*)')

search_regexps = (
    base_search_regexp,
    search_type_regexp,
    search_type_limit_regexp,
    search_type_limit_platform_regexp,
    search_type_limit_platform_version_regexp,
    )

api_patterns = patterns('',
    # Addon_details
    url('addon/(?P<addon_id>\d+)$',
        class_view(views.AddonDetailView),
        name='api.addon_detail'),)

for regexp in search_regexps:
    api_patterns += patterns('',
        url(regexp + '/?$', class_view(views.SearchView), name='api.search'))

urlpatterns = patterns('',
    # Redirect api requests without versions
    url('^((?:addon|search)/.*)$', views.redirect_view),

    # Append api_version to the real api views
    url(r'^(?P<api_version>\d+|\d+.\d+)/', include(api_patterns)),

)
