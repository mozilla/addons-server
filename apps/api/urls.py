from django.conf import settings
from django.conf.urls import include, patterns, url

import waffle
from piston.resource import Resource

from addons.urls import ADDON_ID
from api import authentication, handlers, views, views_drf

API_CACHE_TIMEOUT = getattr(settings, 'API_CACHE_TIMEOUT', 500)


# Wrap class views in a lambda call so we get an fresh instance of the class
# for thread-safety.
def class_view(cls):
    inner = lambda *args, **kw: cls()(*args, **kw)
    return inner


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
ad = {'authentication': authentication.AMOOAuthAuthentication(two_legged=True)}


class SwitchToDRF(object):
    """
    Waffle switch to move from Piston to DRF.
    """
    def __init__(self, resource_name, with_handler=False, with_viewset=False,
                 only_detail=False):
        self.resource_name = resource_name
        self.with_handler = with_handler
        self.with_viewset = with_viewset
        self.only_detail = only_detail

    def __call__(self, *args, **kwargs):
        if waffle.switch_is_active('drf'):
            if self.with_viewset:
                actions = {}
                view_name = self.resource_name + 'ViewSet'
                if self.only_detail:
                    actions = {
                        'get': 'retrieve',
                        'put': 'update',
                        'delete': 'delete',
                    }
                else:
                    actions = {
                        'get': 'retrieve',
                        'post': 'create',
                    }
                return (getattr(views_drf, view_name).as_view(actions)
                        (*args, **kwargs))
            else:
                view_name = self.resource_name + 'View'
                return getattr(views_drf, view_name).as_view()(*args, **kwargs)
        else:
            if self.with_handler:
                handler = getattr(handlers, self.resource_name + 'Handler')
                return Resource(handler=handler, **ad)(*args, **kwargs)
            else:
                return (class_view(getattr(views, self.resource_name + 'View'))
                        (*args, **kwargs))


api_patterns = patterns(
    '',
    # Addon_details
    url('addon/%s$' % ADDON_ID, SwitchToDRF('AddonDetail'),
        name='api.addon_detail'),
    url(r'^get_language_packs$', SwitchToDRF('Language'),
        name='api.language'),)

for regexp in search_regexps:
    api_patterns += patterns(
        '',
        url(regexp + '/?$', SwitchToDRF('Search'), name='api.search'))

for regexp in list_regexps:
    api_patterns += patterns(
        '',
        url(regexp + '/?$', SwitchToDRF('List'), name='api.list'))

piston_patterns = patterns(
    '',
    url(r'^user/$', SwitchToDRF('User', with_handler=True), name='api.user'),
    url(r'^addons/$',
        SwitchToDRF('Addons', with_handler=True, with_viewset=True),
        name='api.addons'),
    url(r'^addon/%s$' % ADDON_ID,
        SwitchToDRF('Addons', with_handler=True, with_viewset=True,
                    only_detail=True),
        name='api.addon'),
    url(r'^addon/%s/versions$' % ADDON_ID,
        SwitchToDRF('Versions', with_handler=True, with_viewset=True),
        name='api.versions'),
    url(r'^addon/%s/version/(?P<version_id>\d+)$' % ADDON_ID,
        SwitchToDRF('Versions', with_handler=True, with_viewset=True,
                    only_detail=True),
        name='api.version'),
)

urlpatterns = patterns(
    '',
    # Redirect api requests without versions
    url('^((?:addon|search|list)/.*)$', views.redirect_view),

    # Piston
    url(r'^2/', include(piston_patterns)),
    url(r'^2/performance/add$', views.performance_add,
        name='api.performance.add'),
    url(r'^1.5/search_suggestions/', views.search_suggestions),
    # Append api_version to the real api views
    url(r'^(?P<api_version>\d+|\d+.\d+)/search/guid:(?P<guids>.*)',
        views.guid_search),
    url(r'^(?P<api_version>\d+|\d+.\d+)/', include(api_patterns)),
)
