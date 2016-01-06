from django.conf import settings
from django.conf.urls import include, patterns, url
from django.contrib import admin
from django.shortcuts import redirect
from django.views.i18n import javascript_catalog
from django.views.decorators.cache import cache_page

from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams
from olympia.versions.urls import download_patterns


admin.autodiscover()

handler403 = 'olympia.amo.views.handler403'
handler404 = 'olympia.amo.views.handler404'
handler500 = 'olympia.amo.views.handler500'


urlpatterns = patterns(
    '',
    # Discovery pane is first for undetectable efficiency wins.
    ('^discovery/', include('olympia.discovery.urls')),

    # There are many more params but we only care about these three. The end is
    # not anchored on purpose!
    url('^blocklist/(?P<apiver>\d+)/(?P<app>[^/]+)/(?P<appver>[^/]+)/',
        'olympia.blocklist.views.blocklist', name='blocklist'),
    ('^blocked/', include('olympia.blocklist.urls')),

    # Home.
    url('^$', 'olympia.addons.views.home', name='home'),

    # Add-ons.
    ('', include('olympia.addons.urls')),

    # Browse pages.
    ('', include('olympia.browse.urls')),

    # Tags.
    ('', include('olympia.tags.urls')),

    # Collections.
    ('', include('olympia.bandwagon.urls')),

    # Files
    ('^files/', include('olympia.files.urls')),

    # Downloads.
    ('^downloads/', include(download_patterns)),

    # Localizer Pages
    ('^localizers/', include('olympia.localizers.urls')),

    # Users
    ('', include('olympia.users.urls')),

    # Developer Hub.
    ('^developers/', include('olympia.devhub.urls')),

    # Developer Hub.
    ('editors/', include('olympia.editors.urls')),

    # AMO admin (not django admin).
    ('^admin/', include('olympia.zadmin.urls')),

    # Localizable pages.
    ('', include('olympia.pages.urls')),

    # App versions.
    ('pages/appversions/', include('olympia.applications.urls')),

    # Services
    ('', include('olympia.amo.urls')),

    # Paypal
    ('^services/', include('olympia.paypal.urls')),

    # Search
    ('^search/', include('olympia.search.urls')),

    # Javascript translations.
    url('^jsi18n.js$', cache_page(60 * 60 * 24 * 7)(javascript_catalog),
        {'domain': 'javascript', 'packages': []}, name='jsi18n'),

    # SAMO/API
    ('^api/', include('olympia.api.urls')),

    ('^compatibility/', include('olympia.compat.urls')),

    # Site events data.
    url('^statistics/events-(?P<start>\d{8})-(?P<end>\d{8}).json$',
        'olympia.stats.views.site_events', name=' amo.site_events'),

    # Site statistics that we are going to catch, the rest will fall through.
    url('^statistics/', include('olympia.stats.urls')),

    # Fall through for any URLs not matched above stats dashboard.
    url('^statistics/', lambda r: redirect('/'), name='statistics.dashboard'),

    # Review spam.
    url('^reviews/spam/$', 'olympia.reviews.views.spam',
        name='addons.reviews.spam'),

    # Redirect patterns.
    ('^bookmarks/?$',
     lambda r: redirect('browse.extensions', 'bookmarks', permanent=True)),

    ('^reviews/display/(\d+)',
     lambda r, id: redirect('addons.reviews.list', id, permanent=True)),

    ('^reviews/add/(\d+)',
     lambda r, id: redirect('addons.reviews.add', id, permanent=True)),

    ('^users/info/(\d+)',
     lambda r, id: redirect('users.profile', id, permanent=True)),

    ('^pages/about$',
     lambda r: redirect('pages.about', permanent=True)),

    ('^pages/credits$',
     lambda r: redirect('pages.credits', permanent=True)),

    ('^pages/faq$',
     lambda r: redirect('pages.faq', permanent=True)),

    # Redirect persona/xxx
    ('^getpersonas$',
     lambda r: redirect('http://www.getpersonas.com/gallery/All/Popular',
                        permanent=True)),

    url('^persona/(?P<persona_id>\d+)',
        'olympia.addons.views.persona_redirect', name='persona'),

    # Redirect top-tags to tags/top
    ('^top-tags/?',
     lambda r: redirect('tags.top_cloud', permanent=True)),

    ('^personas/film and tv/?$',
     lambda r: redirect('browse.personas', 'film-and-tv', permanent=True)),

    ('^addons/versions/(\d+)/?$',
     lambda r, id: redirect('addons.versions', id, permanent=True)),

    ('^addons/versions/(\d+)/format:rss$',
     lambda r, id: redirect('addons.versions.rss', id, permanent=True)),

    # Legacy redirect. Requires a view to get extra data not provided in URL.
    ('^versions/updateInfo/(?P<version_id>\d+)',
     'olympia.versions.views.update_info_redirect'),

    ('^addons/reviews/(\d+)/format:rss$',
     lambda r, id: redirect('addons.reviews.list.rss', id, permanent=True)),

    ('^search-engines.*$',
     lambda r: redirect(urlparams(reverse('search.search'), atype=4),
                        permanent=True)),

    ('^addons/contribute/(\d+)/?$',
     lambda r, id: redirect('addons.contribute', id, permanent=True)),

    ('^recommended$',
     lambda r: redirect(reverse('browse.extensions') + '?sort=featured',
                        permanent=True)),

    ('^recommended/format:rss$',
     lambda r: redirect('browse.featured.rss', permanent=True)),

)

urlpatterns += patterns(
    'piston.authentication.oauth.views',
    url(r'^oauth/request_token/$', 'get_request_token',
        name='oauth.request_token'),
    url(r'^oauth/authorize/$', 'authorize_request_token',
        name='oauth.authorize'),
    url(r'^oauth/access_token/$', 'get_access_token',
        name='oauth.access_token'),
)

if settings.TEMPLATE_DEBUG:
    # Remove leading and trailing slashes so the regex matches.
    media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')

    if 'debug_toolbar' in settings.INSTALLED_APPS:
        import debug_toolbar
        urlpatterns += patterns(
            '',
            url(r'^__debug__/', include(debug_toolbar.urls)),
        )

    urlpatterns += patterns(
        '',
        (r'^%s/(?P<path>.*)$' % media_url, 'django.views.static.serve',
         {'document_root': settings.MEDIA_ROOT}),
    )
