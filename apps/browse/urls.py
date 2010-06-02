from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^language-tools/(?P<category>[^/]+)?$', views.language_tools,
        name='browse.language-tools'),

    url('^themes/(?P<category>[^/]+)?$', views.themes,
        name='browse.themes'),

    url('^extensions/(?:(?P<category>[^/]+)/)?$', views.extensions,
        name='browse.extensions'),

    url('^extensions/(?P<category>[^/]+)/featured$',
        views.creatured, name='browse.creatured'),

    url('^personas/(?P<category>[^ /]+)?$', views.personas,
        name='browse.personas'),

    url('^search-engines/(?:(?P<category>[^/]+)/)?$', views.search_engines,
        name='browse.search-engines'),

    url('^browse/type:(?P<type_>\d)(?:/cat:(?P<category>[^/]+)/?)?',
        views.legacy_redirects),
)
