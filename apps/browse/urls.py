from django.conf.urls.defaults import patterns, url
from django.shortcuts import redirect

from amo.urlresolvers import reverse
from amo.utils import urlparams
from browse.feeds import CategoriesRss, FeaturedRss, SearchToolsRss
from . import views


urlpatterns = patterns('',
    url('^language-tools/(?P<category>[^/]+)?$', views.language_tools,
        name='browse.language-tools'),

    url('^featured$', views.featured, name='browse.featured'),
    # TODO: When we launch the impala pages, add a redirect for this.
    url('^i/featured$',
        lambda r: redirect(reverse('i_browse.extensions') + '?sort=featured',
                           permanent=True)),

    url('^themes/(?P<category>[^/]+)?$', views.themes,
        name='browse.themes'),

    url('^extensions/(?:(?P<category>[^/]+)/)?$', views.extensions,
        name='browse.extensions'),
    url('^es/extensions/(?:(?P<category>[^/]+)/)?$', views.es_extensions,
        name='browse.es.extensions'),
    url('^i/extensions/(?:(?P<category>[^/]+)/)?$', views.impala_extensions,
        name='i_browse.extensions'),

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
