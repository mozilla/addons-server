from django.conf.urls.defaults import patterns, url

from lib.misc.urlconf_decorator import decorate

from amo.decorators import write
from devhub.decorators import use_apps
from webapps.urls import APP_SLUG
from . import views


# These will all start with /submit/app/<app_slug>
submit_apps_patterns = patterns('',
    url('^3$', use_apps(views.describe), name='submit.apps.3'),
    url('^4$', use_apps(views.media), name='submit.apps.4'),
    url('^5$', use_apps(views.done), name='submit.apps.5'),
)


# Decorate all the views as @write so as to bypass cache.
urlpatterns = decorate(write, patterns('',
    # App submission.
    url('^app/submit/$', views.submit, name='submit'),
    url('^app/submit/terms$', views.terms, name='submit.terms'),
    url('^app/submit/describe$', views.describe, name='submit.describe'),
#    url('^app/%s/submit/' % APP_SLUG, include(submit_apps_patterns)),
))
