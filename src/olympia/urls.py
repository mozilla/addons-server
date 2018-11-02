from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin
from django.shortcuts import redirect
from django.views.decorators.cache import cache_page
from django.views.i18n import javascript_catalog
from django.views.static import serve as serve_static

from olympia.addons import views as addons_views
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams
from olympia.stats import views as stats_views
from olympia.versions import views as version_views
from olympia.versions.urls import download_patterns


admin.autodiscover()

handler403 = 'olympia.amo.views.handler403'
handler404 = 'olympia.amo.views.handler404'
handler500 = 'olympia.amo.views.handler500'


urlpatterns = [
    # Legacy Discovery pane is first for undetectable efficiency wins.
    url(r'^discovery/', include('olympia.legacy_discovery.urls')),

    # Home.
    url(r'^$', addons_views.home, name='home'),

    # Add-ons.
    url(r'', include('olympia.addons.urls')),

    # Browse pages.
    url(r'', include('olympia.browse.urls')),

    # Tags.
    url(r'', include('olympia.tags.urls')),

    # Collections.
    url(r'', include('olympia.bandwagon.urls')),

    # Files
    url(r'^files/', include('olympia.files.urls')),

    # Downloads.
    url(r'^downloads/', include(download_patterns)),

    # Users
    url(r'', include('olympia.users.urls')),

    # Developer Hub.
    url(r'^developers/', include('olympia.devhub.urls')),

    # Reviewers Hub.
    url(r'^reviewers/', include('olympia.reviewers.urls')),

    # Redirect everything under editors/ (old reviewer urls) to reviewers/.
    url(r'^editors/(.*)',
        lambda r, path: redirect('/reviewers/%s' % path, permanent=True)),

    # AMO admin (not django admin).
    url(r'^admin/', include('olympia.zadmin.urls')),

    # Localizable pages.
    url(r'', include('olympia.pages.urls')),

    # App versions.
    url(r'pages/appversions/', include('olympia.applications.urls')),

    # Services
    url(r'', include('olympia.amo.urls')),

    # Search
    url(r'^search/', include('olympia.search.urls')),

    # Javascript translations.
    # Should always be called with a cache-busting querystring.
    url(r'^jsi18n\.js$', cache_page(60 * 60 * 24 * 365)(javascript_catalog),
        {'domain': 'djangojs', 'packages': []}, name='jsi18n'),

    # SAMO (Legacy API)
    url(r'^api/', include('olympia.legacy_api.urls')),

    # API v3+.
    url(r'^api/', include('olympia.api.urls')),

    # Site events data.
    url(r'^statistics/events-(?P<start>\d{8})-(?P<end>\d{8})\.json$',
        stats_views.site_events, name='amo.site_events'),

    # Site statistics that we are going to catch, the rest will fall through.
    url(r'^statistics/', include('olympia.stats.urls')),

    # Fall through for any URLs not matched above stats dashboard.
    url(r'^statistics/', lambda r: redirect('/'), name='statistics.dashboard'),

    # Redirect patterns.
    url(r'^bookmarks/?$',
        lambda r: redirect('browse.extensions', 'bookmarks', permanent=True)),

    url(r'^reviews/display/(\d+)',
        lambda r, id: redirect('addons.ratings.list', id, permanent=True)),

    url(r'^reviews/add/(\d+)',
        lambda r, id: redirect('addons.ratings.add', id, permanent=True)),

    url(r'^users/info/(\d+)',
        lambda r, id: redirect('users.profile', id, permanent=True)),

    url(r'^pages/about$',
        lambda r: redirect('pages.about', permanent=True)),

    # Redirect persona/xxx
    url(r'^getpersonas$',
        lambda r: redirect('http://www.getpersonas.com/gallery/All/Popular',
                           permanent=True)),

    url(r'^persona/(?P<persona_id>\d+)',
        addons_views.persona_redirect, name='persona'),

    url(r'^personas/film and tv/?$',
        lambda r: redirect('browse.personas', 'film-and-tv', permanent=True)),

    url(r'^addons/versions/(\d+)/?$',
        lambda r, id: redirect('addons.versions', id, permanent=True)),

    url(r'^addons/versions/(\d+)/format:rss$',
        lambda r, id: redirect('addons.versions.rss', id, permanent=True)),

    # Legacy redirect. Requires a view to get extra data not provided in URL.
    url(r'^versions/updateInfo/(?P<version_id>\d+)',
        version_views.update_info_redirect),

    url(r'^addons/reviews/(\d+)/format:rss$',
        lambda r, id: redirect('addons.ratings.list.rss', id, permanent=True)),

    url(r'^search-engines.*$',
        lambda r: redirect(urlparams(reverse('search.search'), atype=4),
                           permanent=True)),

    url(r'^addons/contribute/(\d+)/?$',
        lambda r, id: redirect('addons.contribute', id, permanent=True)),

    url(r'^recommended$',
        lambda r: redirect(reverse('browse.extensions') + '?sort=featured',
                           permanent=True)),

    url(r'^recommended/format:rss$',
        lambda r: redirect('browse.featured.rss', permanent=True)),
]

if settings.DEBUG:
    # Remove leading and trailing slashes so the regex matches.
    media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')

    urlpatterns.append(
        url(
            r'^%s/(?P<path>.*)$' % media_url,
            serve_static,
            {'document_root': settings.MEDIA_ROOT}),
    )
