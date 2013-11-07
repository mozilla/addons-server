from django.conf import settings
from django.conf.urls import include, patterns, url
from django.contrib import admin
from django.shortcuts import redirect
from django.views.i18n import javascript_catalog
from django.views.decorators.cache import cache_page

from amo.urlresolvers import reverse
from amo.utils import urlparams

import blocklist.views
import versions.urls

admin.autodiscover()

handler403 = 'amo.views.handler403'
handler404 = 'amo.views.handler404'
handler500 = 'amo.views.handler500'


urlpatterns = patterns('',
    # Discovery pane is first for undetectable efficiency wins.
    ('^discovery/', include('discovery.urls')),

    # There are many more params but we only care about these three. The end is
    # not anchored on purpose!
    url('^blocklist/(?P<apiver>\d+)/(?P<app>[^/]+)/(?P<appver>[^/]+)/',
        blocklist.views.blocklist, name='blocklist'),
    ('^blocked/', include('blocklist.urls')),

    # AMO homepage or Marketplace Developer Hub? Choose your destiny.
    url('^$', settings.HOME, name='home'),

    # Add-ons.
    ('', include('addons.urls')),

    # Browse pages.
    ('', include('browse.urls')),

    # Tags.
    ('', include('tags.urls')),

    # Collections.
    ('', include('bandwagon.urls')),

    # Files
    ('^files/', include('files.urls')),

    # Downloads.
    ('^downloads/', include(versions.urls.download_patterns)),

    # Localizer Pages
    ('^localizers/', include('localizers.urls')),

    # Users
    ('', include('users.urls')),

    # Developer Hub.
    ('^developers/', include('devhub.urls')),

    # Developer Hub.
    ('editors/', include('editors.urls')),

    # AMO admin (not django admin).
    ('^admin/', include('zadmin.urls')),

    # Performance wall of shame.
    ('^performance/', include('perf.urls')),

    # Localizable pages.
    ('', include('pages.urls')),

    # App versions.
    ('pages/appversions/', include('applications.urls')),

    # Services
    ('', include('amo.urls')),

    # Paypal
    ('^services/', include('paypal.urls')),

    # Search
    ('^search/', include('search.urls')),

    # Javascript translations.
    url('^jsi18n.js$', cache_page(60 * 60 * 24 * 365)(javascript_catalog),
        {'domain': 'javascript', 'packages': ['zamboni']}, name='jsi18n'),

    # SAMO/API
    ('^api/', include('api.urls')),

    ('^compatibility/', include('compat.urls')),

    # Site events data.
    url('^statistics/events-(?P<start>\d{8})-(?P<end>\d{8}).json$',
        'stats.views.site_events', name='amo.site_events'),

    # Site statistics that we are going to catch, the rest will fall through.
    url('^statistics/', include('stats.urls')),

    # Fall through for any URLs not matched above stats dashboard.
    url('^statistics/', lambda r: redirect('/'), name='statistics.dashboard'),

    # Review spam.
    url('^reviews/spam/$', 'reviews.views.spam', name='addons.reviews.spam'),

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

    url('^persona/(?P<persona_id>\d+)', 'addons.views.persona_redirect',
        name='persona'),

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
     'versions.views.update_info_redirect'),

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

urlpatterns += patterns('piston.authentication.oauth.views',
    url(r'^oauth/request_token/$', 'get_request_token',
        name='oauth.request_token'),
    url(r'^oauth/authorize/$', 'authorize_request_token',
        name='oauth.authorize'),
    url(r'^oauth/access_token/$', 'get_access_token',
        name='oauth.access_token'),
)

if 'django_qunit' in settings.INSTALLED_APPS:

    def _zamboni_qunit(request, path, template):
        from time import time
        import django_qunit.views
        import jingo
        import mock

        # Patch `js` so that CI gets cache-busted JS with TEMPLATE_DEBUG=True.
        # (This will be fixed in `jingo-minify` with bug 717094.)
        from jingo_minify.helpers import _build_html
        import jinja2

        def js(bundle, defer=False, async=False):
            items = settings.MINIFY_BUNDLES['js'][bundle]
            attrs = ['src="%s?v=%s"' % ('%s', time())]
            if defer:
                attrs.append('defer')
            if async:
                attrs.append('async')
            string = '<script %s></script>' % ' '.join(attrs)
            return _build_html(items, string)

        ctx = django_qunit.views.get_suite_context(request, path)
        ctx.update(timestamp=time(), Mock=mock.Mock, js=js)
        response = jingo.render(request, template, ctx)
        # This allows another site to embed the QUnit suite
        # in an iframe (for CI).
        response['x-frame-options'] = ''
        return response

    def zamboni_qunit(request, path):
        return _zamboni_qunit(request, path, 'qunit/qunit.html')

    urlpatterns += patterns('',
        url(r'^qunit/(?P<path>.*)', zamboni_qunit),
        url(r'^_qunit/', include('django_qunit.urls')),
    )

if settings.TEMPLATE_DEBUG:
    # Remove leading and trailing slashes so the regex matches.
    media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')
    urlpatterns += patterns('',
        (r'^%s/(?P<path>.*)$' % media_url, 'django.views.static.serve',
         {'document_root': settings.MEDIA_ROOT}),
    )

if settings.SERVE_TMP_PATH and settings.DEBUG:
    urlpatterns += patterns('',
        (r'^tmp/(?P<path>.*)$', 'django.views.static.serve',
         {'document_root': settings.TMP_PATH}),
    )
