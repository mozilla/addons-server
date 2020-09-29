from django.conf import settings
from django.conf.urls import include
from django.urls import path , re_path
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
    re_path(r'^discovery/.*', lambda request: redirect(
        'https://www.mozilla.org/firefox/new/', permanent=True)),

    # Home.
    path('', frontend_view, name='home'),

    # Add-ons.
    path('', include('olympia.addons.urls')),

    # Browse pages.
    path('', include('olympia.browse.urls')),

    # Tags.
    path('', include('olympia.tags.urls')),

    # Collections.
    path('', include('olympia.bandwagon.urls')),

    # Do not expose the `upload_patterns` under `files/` because of this issue:
    # https://github.com/mozilla/addons-server/issues/12322
    path('uploads/', include(upload_patterns)),

    # Downloads.
    path('downloads/', include(download_patterns)),

    # Users
    path('', include('olympia.users.urls')),

    # Developer Hub.
    path('developers/', include('olympia.devhub.urls')),

    # Reviewers Hub.
    path('reviewers/', include('olympia.reviewers.urls')),

    # Redirect everything under editors/ (old reviewer urls) to reviewers/.
    path('editors/<str:path>/',
        lambda r, path: redirect('/reviewers/%s' % path, permanent=True)),

    # AMO admin (not django admin).
    path('admin', include('olympia.zadmin.urls')),

    # Localizable pages.
    path('', include('olympia.pages.urls')),

    # App versions.
    path('pages/appversions/', include('olympia.applications.urls')),

    # Services
    path('', include('olympia.amo.urls')),

    # Search
    path('search/', include('olympia.search.urls')),

    # API v3+.
    path('api/', include('olympia.api.urls')),

    # Redirect for all global stats URLs.
    path('statistics/', lambda r: redirect('/'), name='statistics.dashboard'),

    # Redirect patterns.
    path('bookmarks/',
        lambda r: redirect('browse.extensions', 'bookmarks', permanent=True)),

    path('pages/about/',
        lambda r: redirect('pages.about', permanent=True)),

    path('addons/versions/<int:id>/',
        lambda r, id: redirect('addons.versions', id, permanent=True)),

    # Legacy redirect. Requires a view to get extra data not provided in URL.
    path('versions/updateInfo/<int:version_id>/',
        version_views.update_info_redirect),

    re_path(r'^search-engines.*$',
        lambda r: redirect(urlparams(reverse('search.search'), atype=4),
                           permanent=True)),

    path('addons/contribute/<int:id>/',
        lambda r, id: redirect('addons.contribute', id, permanent=True)),
]

if settings.DEBUG:
    import debug_toolbar

    # Remove leading and trailing slashes so the regex matches.
    media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')

    urlpatterns.extend([
        re_path(r'^%s/(?P<path>.*)$' % media_url,
            serve_static,
            {'document_root': settings.MEDIA_ROOT}),
        re_path(r'__debug__/', include(debug_toolbar.urls)),
    ])
