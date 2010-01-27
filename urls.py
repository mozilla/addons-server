from django.conf import settings
from django.conf.urls.defaults import patterns, url, include
from django.contrib import admin

admin.autodiscover()


urlpatterns = patterns('',
    url('^$', 'jingo.views.direct_to_template',
        {'template': 'base.html'}, name='home'),

    # Add-ons.
    ('', include('addons.urls')),

    # Users
    ('^users/', include('users.urls')),

    # AMO admin (not django admin).
    ('^admin/', include('admin.urls')),
)

if settings.DEBUG:
    # Remove leading and trailing slashes so the regex matches.
    media_url = settings.MEDIA_URL.lstrip('/').rstrip('/')
    urlpatterns += patterns('',
        (r'^%s/(?P<path>.*)$' % media_url, 'django.views.static.serve',
         {'document_root': settings.MEDIA_ROOT}),
    )
