from django.conf.urls.defaults import include, patterns, url

from lib.misc.urlconf_decorator import decorate

from amo.decorators import write
from webapps.urls import APP_SLUG
from . import views


# These URLs start with /developers/submit/app/<app_slug>/.
submit_apps_patterns = patterns('',
    url('^details$', views.details, name='submit.app.details'),
    url('^payments$', views.payments, name='submit.app.payments'),
    url('^done$', views.done, name='submit.app.done'),
)


# Decorate all the views as @write so as to bypass cache.
urlpatterns = decorate(write, patterns('',
    # App submission.
    url('^$', views.submit, name='submit.app'),
    url('^terms$', views.terms, name='submit.app.terms'),
    url('^manifest$', views.manifest, name='submit.app.manifest'),
    url('^app/%s/submit/' % APP_SLUG, include(submit_apps_patterns)),
))
