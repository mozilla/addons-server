from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin
from django.shortcuts import redirect
from django.views.static import serve as serve_static

from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams
from olympia.amo.views import frontend_view
from olympia.files.urls import upload_patterns
from olympia.versions import views as version_views
from olympia.versions.urls import download_patterns


admin.autodiscover()

handler403 = 'olympia.amo.views.handler403'
handler404 = 'olympia.amo.views.handler404'
handler500 = 'olympia.amo.views.handler500'


urlpatterns = [
    # Legacy Discovery pane is first for undetectable efficiency wins.
    url(r'^discovery/.*', lambda request: redirect(
        'https://www.mozilla.org/firefox/new/', permanent=True)),

    # Home.
    url(r'^$', frontend_view, name='home'),

    # Add-ons.
    url(r'', include('olympia.addons.urls')),

    # Browse pages.
    url(r'', include('olympia.browse.urls')),

    # Tags.
    url(r'', include('olympia.tags.urls')),

    # Collections.
    url(r'', include('olympia.bandwagon.urls')),

    # Do not expose the `upload_patterns` under `files/` because of this issue:
    # https://github.com/mozilla/addons-server/issues/12322
    url(r'^uploads/', include(upload_patterns)),

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

    # API v3+.
    url(r'^api/', include('olympia.api.urls')),

    # Redirect for all global stats URLs.
    url(r'^statistics/', lambda r: redirect('/'), name='statistics.dashboard'),

    # Redirect patterns.
    url(r'^bookmarks/?$',
        lambda r: redirect('browse.extensions', 'bookmarks', permanent=True)),

    url(r'^pages/about$',
        lambda r: redirect('pages.about', permanent=True)),

    url(r'^addons/versions/(\d+)/?$',
        lambda r, id: redirect('addons.versions', id, permanent=True)),

    # Legacy redirect. Requires a view to get extra data not provided in URL.
    url(r'^versions/updateInfo/(?P<version_id>\d+)',
        version_views.update_info_redirect),

    url(r'^search-engines.*$',
        lambda r: redirect(urlparams(reverse('search.search'), atype=4),
                           permanent=True)),

    url(r'^addons/contribute/(\d+)/?$',
        lambda r, id: redirect('addons.contribute', id, permanent=True)),
]

if settings.DEBUG:
    import debug_toolbar

    # Remove leading and trailing slashes so the regex matches.
    media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')

    urlpatterns.extend([
        url(r'^%s/(?P<path>.*)$' % media_url,
            serve_static,
            {'document_root': settings.MEDIA_ROOT}),
        url(r'__debug__/', include(debug_toolbar.urls)),
    ])
