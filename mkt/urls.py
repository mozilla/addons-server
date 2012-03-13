from django.conf import settings
from django.conf.urls.defaults import patterns, url, include
from django.contrib import admin
from django.views.decorators.cache import cache_page
from django.views.i18n import javascript_catalog

from apps.users.views import logout
from mkt.developers.views import login


admin.autodiscover()

handler404 = 'mkt.site.views.handler404'
handler500 = 'mkt.site.views.handler500'

APP_SLUG = r"""(?P<app_slug>[^/<>"']+)"""

# These URLs take precedence over existing ones.
urlpatterns = patterns('',
    # Replace the "old" Developer Hub with the "new" Marketplace one.
    ('^developers/', include('mkt.developers.urls')),

    # Submission.
    ('^developers/submit/app/', include('mkt.submit.urls')),

    # Misc pages.
    ('', include('mkt.site.urls')),

    # Editor tools.
    ('editors/', include('editors.urls')),

    # Home.
    url('$^', settings.HOME, name='home'),

    # Services.
    ('', include('apps.amo.urls')),

    ('^app/%s/' % APP_SLUG, include('mkt.detail.urls')),

    # Web apps.
    ('^apps/', include('webapps.urls')),

    # Users.
    ('', include('users.urls')),

    # Javascript translations.
    url('^jsi18n.js$', cache_page(60 * 60 * 24 * 365)(javascript_catalog),
        {'domain': 'javascript', 'packages': ['zamboni']}, name='jsi18n'),

    # Paypal, needed for IPNs only.
    ('', include('paypal.urls')),

    # AMO admin (not django admin).
    ('^admin/', include('zadmin.urls')),

    # Accept extra junk at the end for a cache-busting build id.
    url('^addons/buttons.js(?:/.+)?$', 'addons.buttons.js'),
)


# Override old patterns.
urlpatterns += patterns('',
    # Developer Registration Login.
    url('^login$', login, name='users.login'),
    url('^logout$', logout, name='users.logout'),
)


# Marketplace UI Experiments.
if getattr(settings, 'POTCH_MARKETPLACE_EXPERIMENTS', False):
    urlpatterns += patterns('',
        ('^marketplace-experiments/', include('mkt.experiments.urls'))
    )


if settings.TEMPLATE_DEBUG:
    # Remove leading and trailing slashes so the regex matches.
    media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')
    urlpatterns += patterns('',
        (r'^%s/(?P<path>.*)$' % media_url, 'django.views.static.serve',
         {'document_root': settings.MEDIA_ROOT}),
    )


if settings.SERVE_TMP_PATH and settings.DEBUG:
    # Serves any URL like /tmp/* from your local ./tmp/ dir
    urlpatterns += patterns('',
        (r'^tmp/(?P<path>.*)$', 'django.views.static.serve',
         {'document_root': settings.TMP_PATH}),
    )
