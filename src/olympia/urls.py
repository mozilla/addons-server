from django.conf import settings
from django.urls import include, re_path
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
    re_path(
        r'^discovery/.*',
        lambda request: redirect(
            'https://www.mozilla.org/firefox/new/', permanent=True
        ),
    ),
    # Home.
    re_path(r'^$', frontend_view, name='home'),
    # Add-ons.
    re_path(r'', include('olympia.addons.urls')),
    # Browse pages.
    re_path(r'', include('olympia.browse.urls')),
    # Tags.
    re_path(r'', include('olympia.tags.urls')),
    # Collections.
    re_path(r'', include('olympia.bandwagon.urls')),
    # Do not expose the `upload_patterns` under `files/` because of this issue:
    # https://github.com/mozilla/addons-server/issues/12322
    re_path(r'^uploads/', include(upload_patterns)),
    # Downloads.
    re_path(r'^downloads/', include(download_patterns)),
    # Users
    re_path(r'', include('olympia.users.urls')),
    # Developer Hub.
    re_path(r'^developers/', include('olympia.devhub.urls')),
    # Reviewers Hub.
    re_path(r'^reviewers/', include('olympia.reviewers.urls')),
    # Redirect everything under editors/ (old reviewer urls) to reviewers/.
    re_path(
        r'^editors/(.*)',
        lambda r, path: redirect('/reviewers/%s' % path, permanent=True),
    ),
    # AMO admin (not django admin).
    re_path(r'^admin/', include('olympia.zadmin.urls')),
    # Localizable pages.
    re_path(r'', include('olympia.pages.urls')),
    # App versions.
    re_path(r'pages/appversions/', include('olympia.applications.urls')),
    # Services
    re_path(r'', include('olympia.amo.urls')),
    # Search
    re_path(r'^search/', include('olympia.search.urls')),
    # API v3+.
    re_path(r'^api/', include('olympia.api.urls')),
    # Redirect for all global stats URLs.
    re_path(r'^statistics/', lambda r: redirect('/'), name='statistics.dashboard'),
    # Redirect patterns.
    re_path(
        r'^bookmarks/?$',
        lambda r: redirect('browse.extensions', 'bookmarks', permanent=True),
    ),
    re_path(r'^pages/about$', lambda r: redirect('pages.about', permanent=True)),
    re_path(
        r'^addons/versions/(\d+)/?$',
        lambda r, id: redirect('addons.versions', id, permanent=True),
    ),
    # Legacy redirect. Requires a view to get extra data not provided in URL.
    re_path(
        r'^versions/updateInfo/(?P<version_id>\d+)', version_views.update_info_redirect
    ),
    re_path(
        r'^search-engines.*$',
        lambda r: redirect(
            urlparams(reverse('search.search'), atype=4), permanent=True
        ),
    ),
    re_path(
        r'^addons/contribute/(\d+)/?$',
        lambda r, id: redirect('addons.contribute', id, permanent=True),
    ),
]

if settings.DEBUG:
    import debug_toolbar

    # Remove leading and trailing slashes so the regex matches.
    media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')

    urlpatterns.extend(
        [
            re_path(
                r'^%s/(?P<path>.*)$' % media_url,
                serve_static,
                {'document_root': settings.MEDIA_ROOT},
            ),
            re_path(r'__debug__/', include(debug_toolbar.urls)),
        ]
    )
