from django.conf.urls import include, patterns, url
from django.shortcuts import redirect

from lib.misc.urlconf_decorator import decorate

from addons.urls import ADDON_ID
import amo
from amo.decorators import write
from devhub import views as devhub_views
from . import views


# These URLs start with /developers/submit/app/<app_slug>/.
submit_apps_patterns = patterns('',
    url('^details/%s$' % amo.APP_SLUG, views.details,
        name='submit.app.details'),
    url('^done/%s$' % amo.APP_SLUG, views.done, name='submit.app.done'),
    url('^resume/%s$' % amo.APP_SLUG, views.resume, name='submit.app.resume'),
)


# Decorate all the views as @write so as to bypass cache.
urlpatterns = decorate(write, patterns('',
    url('^theme$', views.submit_theme, name='submit.theme'),
    url('^theme/upload/'
        '(?P<upload_type>persona_header|persona_footer)$',
        devhub_views.ajax_upload_image, name='submit.theme.upload'),
    url('^theme/%s$' % ADDON_ID, views.submit_theme_done,
        name='submit.theme.done'),

    # Legacy redirects for app submission.
    ('^app', lambda r: redirect('submit.app')),
    # ^ So we can avoid an additional redirect below.
    ('^app/.*', lambda r: redirect(r.path.replace('/developers/app',
                                                  '/developers', 1))),
    ('^manifest$', lambda r: redirect('submit.app', permanent=True)),

    # App submission.
    url('^$', views.submit, name='submit.app'),
    url('^terms$', views.terms, name='submit.app.terms'),

    ('', include(submit_apps_patterns)),
))
