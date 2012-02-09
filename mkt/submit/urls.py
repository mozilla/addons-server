from django.conf.urls.defaults import patterns, url, include
from django.shortcuts import redirect

from lib.misc.urlconf_decorator import decorate

from amo.decorators import write
from devhub.decorators import use_apps
import devhub.views
from webapps.urls import APP_SLUG
from . import views

# TODO: Rename `hub` app to `submit`.


# These will all start with /submit/app/<app_slug>
submit_apps_patterns = patterns('',
    url('^3$', use_apps(views.describe), name='submit.apps.3'),
    url('^4$', use_apps(views.media), name='submit.apps.4'),
    url('^5$', use_apps(views.done), name='submit.apps.5'),
)


# Decorate all the views as @write so as to bypass cache.
urlpatterns = decorate(write, patterns('',
    # App submission.
    url('^app/submit/$', lambda r: redirect('submit.apps.1')),
    url('^app/submit/1$', views.terms, name='submit.apps.1'),
#    url('^app/submit/2$', use_apps(devhub.views.submit_addon),
#        name='hub.submit_apps.2'),
#    url('^app/%s/submit/' % APP_SLUG, include(submit_apps_patterns)),
))
