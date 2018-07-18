from django.conf.urls import include, url
from django.shortcuts import redirect

from olympia.amo.urlresolvers import reverse
from olympia.browse.feeds import (
    ExtensionCategoriesRss,
    FeaturedRss,
    SearchToolsRss,
    ThemeCategoriesRss,
)

from . import views


impala_patterns = [
    # TODO: Impalacize these views.
    url(
        '^extensions/(?P<category>[^/]+)/featured$',
        views.legacy_creatured_redirect,
        name='i_browse.creatured',
    ),
    url(
        '^language-tools/(?P<category>[^/]+)?$',
        views.language_tools,
        name='i_browse.language-tools',
    ),
    url(
        '^search-tools/(?P<category>[^/]+)?$',
        views.search_tools,
        name='i_browse.search-tools',
    ),
]

urlpatterns = [
    url('^i/', include(impala_patterns)),
    url(
        '^language-tools/(?P<category>[^/]+)?$',
        views.language_tools,
        name='browse.language-tools',
    ),
    url(
        '^dictionaries$',
        lambda r: redirect(reverse('browse.language-tools'), permanent=True),
    ),
    url(
        '^featured$',
        lambda r: redirect(
            reverse('browse.extensions') + '?sort=featured', permanent=True
        ),
    ),
    # Full Themes are now Complete Themes.
    url(
        '^full-themes/(?P<category>[^ /]+)?$', views.legacy_fulltheme_redirects
    ),
    # Personas are now Themes.
    url('^personas/(?P<category>[^ /]+)?$', views.legacy_theme_redirects),
    url(
        '^themes/(?:(?P<category>[^ /]+)/)?$',
        views.personas,
        name='browse.personas',
    ),
    # Themes are now Complete Themes.
    url(
        '^themes/(?P<category_name>[^/]+)/format:rss$',
        views.legacy_theme_redirects,
    ),
    url(
        '^complete-themes/(?P<category>[^/]+)?$',
        views.themes,
        name='browse.themes',
    ),
    url(
        '^complete-themes/(?:(?P<category_name>[^/]+)/)?format:rss$',
        ThemeCategoriesRss(),
        name='browse.themes.rss',
    ),
    # This won't let you browse any themes but detail page needs the url.
    url(
        '^static-themes/(?:(?P<category>[^/]+)/)?$',
        lambda r, category: redirect(
            reverse(
                'browse.personas',
                kwargs=({'category': category} if category else {}),
            )
        ),
        name='browse.static-themes',
    ),
    url(
        '^extensions/(?:(?P<category>[^/]+)/)?$',
        views.extensions,
        name='browse.extensions',
    ),
    # Creatured URLs now redirect to browse.extensions
    url(
        '^extensions/(?P<category>[^/]+)/featured$',
        views.legacy_creatured_redirect,
    ),
    url(
        '^extensions/(?:(?P<category_name>[^/]+)/)?format:rss$',
        ExtensionCategoriesRss(),
        name='browse.extensions.rss',
    ),
    url(
        '^browse/type:7$',
        lambda r: redirect(
            "https://www.mozilla.org/plugincheck/", permanent=True
        ),
    ),
    url(
        '^browse/type:(?P<type_>\d)(?:/cat:(?P<category>\d+))?'
        '(?:/sort:(?P<sort>[^/]+))?(?:/format:(?P<format>[^/]+).*)?',
        views.legacy_redirects,
    ),
    url(
        '^search-tools/(?:(?P<category>[^/]+)/)?format:rss$',
        SearchToolsRss(),
        name='browse.search-tools.rss',
    ),
    url(
        '^search-tools/(?P<category>[^/]+)?$',
        views.search_tools,
        name='browse.search-tools',
    ),
    url('^featured/format:rss$', FeaturedRss(), name='browse.featured.rss'),
    # The plugins page was moved to mozilla.org and so now it is just a
    # redirect, per bug 775799.
    url(
        '^plugins$',
        lambda r: redirect(
            'http://www.mozilla.org/en-US/plugincheck/', permanent=True
        ),
    ),
]
