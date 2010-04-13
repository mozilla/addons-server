from django.conf import settings
from django.conf.urls.defaults import patterns, url, include
from django.contrib import admin
from django.shortcuts import redirect

admin.autodiscover()

handler404 = 'amo.views.handler404'
handler500 = 'amo.views.handler500'

urlpatterns = patterns('',
    # Add-ons.
    ('', include('addons.urls')),

    # Browse pages.
    ('', include('browse.urls')),

    # Users
    ('', include('users.urls')),

    # AMO admin (not django admin).
    ('^admin/', include('zadmin.urls')),

    # Nick's special pages.
    ('^nickspages/', include('nick.urls')),

    # Localizable pages.
    ('', include('pages.urls')),

    # Services
    ('^services/', include('amo.urls')),

    # Search
    ('^search/', include('search.urls')),

    # Global stats dashboard.
    url('^statistics/', lambda r: redirect('/'), name='statistics.dashboard'),

    # Javascript translations.
    ('^jsi18n/$', 'django.views.i18n.javascript_catalog',
     {'domain': 'z-javascript', 'packages': ['zamboni']}),

    # SAMO/API
    ('^api/', include('api.urls')),

    # Redirect patterns.
    ('^reviews/display/(\d+)',
      lambda r, id: redirect('reviews.list', id, permanent=True)),

    ('^users/info/(\d+)',
     lambda r, id: redirect('users.profile', id, permanent=True)),

    ('^browse/type:3$',
      lambda r: redirect('browse.language_tools', permanent=True)),

    ('^browse/type:2.*$',
     lambda r: redirect('browse.themes', permanent=True)),

    ('^pages/about$',
     lambda r: redirect('pages.about', permanent=True)),
    ('^pages/faq$',
     lambda r: redirect('pages.faq', permanent=True)),
)

if settings.DEBUG:
    # Remove leading and trailing slashes so the regex matches.
    media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')
    urlpatterns += patterns('',
        (r'^%s/(?P<path>.*)$' % media_url, 'django.views.static.serve',
         {'document_root': settings.MEDIA_ROOT}),
    )
