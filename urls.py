from django.conf import settings
from django.conf.urls.defaults import patterns, url, include
from django.contrib import admin
from django.shortcuts import redirect
from django.views.i18n import javascript_catalog
from django.views.decorators.cache import cache_page

import versions.urls

admin.autodiscover()

handler404 = 'amo.views.handler404'
handler500 = 'amo.views.handler500'

urlpatterns = patterns('',
    # Discovery pane is first for undetectable efficiency wins.
    ('^discovery/', include('discovery.urls')),

    # Add-ons.
    ('', include('addons.urls')),

    # Browse pages.
    ('', include('browse.urls')),

    # Tags.
    ('', include('tags.urls')),

    # Collections.
    ('', include('bandwagon.urls')),

    # Downloads.
    ('^downloads/', include(versions.urls.download_patterns)),

    # Users
    ('', include('users.urls')),

    # Tags
    ('', include('tags.urls')),

    # Developer Hub.
    ('developers/', include('devhub.urls')),

    # AMO admin (not django admin).
    ('^admin/', include('zadmin.urls')),

    # Nick's special pages.
    ('^nickspages/', include('nick.urls')),

    # Localizable pages.
    ('', include('pages.urls')),

    # App versions.
    ('pages/appversions/', include('applications.urls')),

    # Services
    ('', include('amo.urls')),

    # Search
    ('^search/', include('search.urls')),

    # Global stats dashboard.
    url('^statistics/', lambda r: redirect('/'), name='statistics.dashboard'),

    # Javascript translations.
    url('^jsi18n/.*$', cache_page(60 * 60 * 24 * 365)(javascript_catalog),
        {'domain': 'z-javascript', 'packages': ['zamboni']}, name='jsi18n'),

    # SAMO/API
    ('^api/', include('api.urls')),

    # Review spam.
    url('^reviews/spam/$', 'reviews.views.spam', name='reviews.spam'),

    # Redirect patterns.
    ('^bookmarks/?$',
      lambda r: redirect('browse.extensions', 'bookmarks', permanent=True)),

    ('^reviews/display/(\d+)',
      lambda r, id: redirect('reviews.list', id, permanent=True)),

    ('^reviews/add/(\d+)',
      lambda r, id: redirect('reviews.add', id, permanent=True)),

    ('^users/info/(\d+)',
     lambda r, id: redirect('users.profile', id, permanent=True)),

    ('^pages/about$',
     lambda r: redirect('pages.about', permanent=True)),

    ('^pages/faq$',
     lambda r: redirect('pages.faq', permanent=True)),

    # Redirect persona/xxx
    ('^persona/(\d+)',
     lambda r, id: redirect('addons.detail', id, permanent=True)),

    # Redirect top-tags to tags/top
    ('^top-tags/?',
     lambda r: redirect('tags.top_cloud', permanent=True)),

    ('^personas/film and tv/?$',
     lambda r: redirect('browse.personas', 'film-and-tv', permanent=True)),

    ('^addons/versions/(\d+)/?$',
     lambda r, id: redirect('addons.versions', id, permanent=True)),

    ('^addons/versions/(\d+)/format:rss$',
     lambda r, id: redirect('addons.versions.rss', id, permanent=True)),

    ('^addons/reviews/(\d+)/format:rss$',
     lambda r, id: redirect('reviews.list.rss', id, permanent=True)),

    ('^search-engines.*$',
     lambda r: redirect('browse.search-tools', permanent=True)),

    ('^addons/contribute/(\d+)/?$',
     lambda r, id: redirect('addons.contribute', id, permanent=True)),

    ('^recommended$',
     lambda r: redirect('browse.featured', permanent=True)),

    ('^recommended/format:rss$',
     lambda r: redirect('browse.featured.rss', permanent=True)),

)

urlpatterns += patterns('piston.authentication',
    url(r'^oauth/request_token/$', 'oauth_request_token',
        name='oauth.request_token'),
    url(r'^oauth/authorize/$', 'oauth_user_auth', name='oauth.authorize'),
    url(r'^oauth/access_token/$', 'oauth_access_token',
        name='oauth.access_token'),
)

if settings.DEBUG:
    # Remove leading and trailing slashes so the regex matches.
    media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')
    urlpatterns += patterns('',
        (r'^%s/(?P<path>.*)$' % media_url, 'django.views.static.serve',
         {'document_root': settings.MEDIA_ROOT}),
    )
