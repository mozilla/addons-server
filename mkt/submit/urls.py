from django.conf.urls.defaults import include, patterns, url

from lib.misc.urlconf_decorator import decorate

from amo.decorators import write
from mkt.webapps.urls import APP_SLUG
from . import views


# These URLs start with /developers/submit/app/<app_slug>/.
submit_apps_patterns = patterns('',
    url('^details/%s$' % APP_SLUG, views.details, name='submit.app.details'),
    url('^payments/%s$' % APP_SLUG, views.payments,
        name='submit.app.payments'),
    url('^payments/upsell/%s$' % APP_SLUG, views.payments_upsell,
        name='submit.app.payments.upsell'),
    url('^payments/paypal/%s$' % APP_SLUG, views.payments_paypal,
        name='submit.app.payments.paypal'),
    url('^payments/bounce/%s$' % APP_SLUG, views.payments_bounce,
        name='submit.app.payments.bounce'),
    url('^payments/confirm/%s$' % APP_SLUG, views.payments_confirm,
        name='submit.app.payments.confirm'),
    url('^done/%s$' % APP_SLUG, views.done, name='submit.app.done'),
    url('^resume/%s$' % APP_SLUG, views.resume, name='submit.app.resume'),
)


# Decorate all the views as @write so as to bypass cache.
urlpatterns = decorate(write, patterns('',
    # App submission.
    url('^$', views.submit, name='submit.app'),
    url('^terms$', views.terms, name='submit.app.terms'),
    url('^manifest$', views.manifest, name='submit.app.manifest'),
    ('', include(submit_apps_patterns)),
))
