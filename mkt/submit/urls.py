from django.conf.urls import include, patterns, url

from lib.misc.urlconf_decorator import decorate

import amo
from amo.decorators import write
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
    # App submission.
    url('^$', views.submit, name='submit.app'),
    url('^terms$', views.terms, name='submit.app.terms'),
    url('^choose$', views.choose, name='submit.app.choose'),
    url('^manifest$', views.manifest, name='submit.app.manifest'),
    url('^package$', views.package, name='submit.app.package'),
    ('', include(submit_apps_patterns)),
))
