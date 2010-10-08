from django.conf.urls.defaults import patterns, url
from browse.feeds import CategoriesRss
from . import views
from browse.feeds import FeaturedRss


urlpatterns = patterns('',
    url('^language-tools/(?P<category>[^/]+)?$', views.language_tools,
        name='browse.language-tools'),

    url('^featured$', views.featured, name='browse.featured'),

    url('^themes/(?P<category>[^/]+)?$', views.themes,
        name='browse.themes'),

    url('^extensions/(?:(?P<category>[^/]+)/)?$', views.extensions,
        name='browse.extensions'),

    url('^extensions/(?P<category>[^/]+)/featured$',
        views.creatured, name='browse.creatured'),

    url('^extensions/(?:(?P<category_name>[^/]+)/)?format:rss$', CategoriesRss(),
        name='browse.extensions.rss'),

    url('^personas/(?P<category>[^ /]+)?$', views.personas,
        name='browse.personas'),

    url('^browse/type:(?P<type_>\d)(?:/cat:(?P<category>\d+))?'
        '(?:/sort:(?P<sort>[^/]+))?(?:/format:(?P<format>[^/]+).*)?',
        views.legacy_redirects),

    url('^search-tools/(?P<category>[^/]+)?$', views.search_tools,
        name='browse.search-tools'),

    url('^featured/format:rss$', FeaturedRss(), name='browse.featured.rss'),
)
