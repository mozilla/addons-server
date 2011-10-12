from django.conf.urls.defaults import include, patterns, url
from django.shortcuts import redirect

from amo.urlresolvers import reverse
from browse.feeds import CategoriesRss, FeaturedRss, SearchToolsRss
from . import views

impala_patterns = patterns('',
    # TODO: Impalacize these views.
    url('^extensions/(?P<category>[^/]+)/featured$', views.creatured,
        name='i_browse.creatured'),
    url('^personas/(?P<category>[^ /]+)?$', views.personas,
        name='i_browse.personas'),
    url('^language-tools/(?P<category>[^/]+)?$', views.language_tools,
        name='i_browse.language-tools'),
    url('^search-tools/(?P<category>[^/]+)?$', views.search_tools,
        name='i_browse.search-tools'),
)

urlpatterns = patterns('',
    url('^i/', include(impala_patterns)),

    url('^language-tools/(?P<category>[^/]+)?$', views.language_tools,
        name='browse.language-tools'),

    url('^featured$',
        lambda r: redirect(reverse('browse.extensions') + '?sort=featured',
                           permanent=True)),

    url('^themes/(?P<category>[^/]+)?$', views.themes,
        name='browse.themes'),

    url('^extensions/(?:(?P<category>[^/]+)/)?$', views.extensions,
        name='browse.extensions'),
    url('^es/extensions/(?:(?P<category>[^/]+)/)?$', views.es_extensions,
        name='browse.es.extensions'),

    url('^extensions/(?P<category>[^/]+)/featured$',
        views.creatured, name='browse.creatured'),

    url('^extensions/(?:(?P<category_name>[^/]+)/)?format:rss$',
        CategoriesRss(), name='browse.extensions.rss'),

    url('^personas/(?P<category>[^ /]+)?$', views.personas,
        name='browse.personas'),

    url('^browse/type:(?P<type_>\d)(?:/cat:(?P<category>\d+))?'
        '(?:/sort:(?P<sort>[^/]+))?(?:/format:(?P<format>[^/]+).*)?',
        views.legacy_redirects),

    url('^search-tools/(?:(?P<category>[^/]+)/)?format:rss$',
        SearchToolsRss(), name='browse.search-tools.rss'),

    url('^search-tools/(?P<category>[^/]+)?$', views.search_tools,
        name='browse.search-tools'),

    url('^featured/format:rss$', FeaturedRss(), name='browse.featured.rss'),
)
