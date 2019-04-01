from django.conf.urls import url

from olympia.amo.views import frontend_view


urlpatterns = [
    url(r'^language-tools/(?P<category>[^/]+)?$', frontend_view,
        name='browse.language-tools'),
    url(r'^themes/(?P<category>[^/]+)?$', frontend_view,
        name='browse.themes'),
    url(r'^extensions/(?:(?P<category>[^/]+)/)?$', frontend_view,
        name='browse.extensions'),
    url(r'^search-tools/(?P<category>[^/]+)?$', frontend_view,
        name='browse.search-tools'),
]
