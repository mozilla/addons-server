from django.conf.urls import include, patterns, url
from django.shortcuts import redirect

from amo.urlresolvers import reverse
from browse.feeds import (ExtensionCategoriesRss, FeaturedRss, SearchToolsRss,
                          ThemeCategoriesRss)
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

    url('^dictionaries$',
        lambda r: redirect(reverse('browse.language-tools'), permanent=True)),

    url('^featured$',
        lambda r: redirect(reverse('browse.extensions') + '?sort=featured',
                           permanent=True)),

    url('^(?:themes|extensions)/moreinfo.php$', views.moreinfo_redirect),

    url('^themes/(?P<category>[^/]+)?$', views.themes,
        name='browse.themes'),
    url('^themes/(?:(?P<category_name>[^/]+)/)?format:rss$',
        ThemeCategoriesRss(), name='browse.themes.rss'),

    url('^extensions/(?:(?P<category>[^/]+)/)?$', views.extensions,
        name='browse.extensions'),
    url('^es/extensions/(?:(?P<category>[^/]+)/)?$', views.es_extensions,
        name='browse.es.extensions'),

    url('^extensions/(?P<category>[^/]+)/featured$',
        views.creatured, name='browse.creatured'),

    url('^extensions/(?:(?P<category_name>[^/]+)/)?format:rss$',
        ExtensionCategoriesRss(), name='browse.extensions.rss'),

    url('^personas/(?P<category>[^ /]+)?$', views.personas,
        name='browse.personas'),

    url('^browse/type:7$',
        lambda r: redirect("https://www.mozilla.org/plugincheck/",
                            permanent=True)),

    url('^browse/type:(?P<type_>\d)(?:/cat:(?P<category>\d+))?'
        '(?:/sort:(?P<sort>[^/]+))?(?:/format:(?P<format>[^/]+).*)?',
        views.legacy_redirects),

    url('^search-tools/(?:(?P<category>[^/]+)/)?format:rss$',
        SearchToolsRss(), name='browse.search-tools.rss'),

    url('^search-tools/(?P<category>[^/]+)?$', views.search_tools,
        name='browse.search-tools'),

    url('^featured/format:rss$', FeaturedRss(), name='browse.featured.rss'),

    # The plugins page was moved to mozilla.org and so now it is just a
    # redirect, per bug 775799.
    url('^plugins$',
        lambda r: redirect('http://www.mozilla.org/en-US/plugincheck/',
                           permanent=True)),
)
