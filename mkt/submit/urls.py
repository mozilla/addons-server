from django.conf.urls.defaults import include, patterns, url

from lib.misc.urlconf_decorator import decorate

from amo.decorators import write
from webapps.urls import APP_SLUG
from . import views


# These URLs start with /developers/submit/app/<app_slug>/.
submit_apps_patterns = patterns('',
    url('^details/%s$' % APP_SLUG, views.details, name='submit.app.details'),
    url('^payments/%s$' % APP_SLUG, views.payments,
        name='submit.app.payments'),
    url('^done/%s$' % APP_SLUG, views.done, name='submit.app.done'),
)


# Decorate all the views as @write so as to bypass cache.
urlpatterns = decorate(write, patterns('',
    # App submission.
    url('^$', views.submit, name='submit.app'),
    url('^terms$', views.terms, name='submit.app.terms'),
    url('^manifest$', views.manifest, name='submit.app.manifest'),
    ('', include(submit_apps_patterns)),
))
