from django.conf.urls.defaults import patterns, url, include

from lib.misc.urlconf_decorator import decorate

from amo.decorators import write
from . import views


# Decorate all the views as @write so as to bypass cache.
urlpatterns = decorate(write, patterns('',
    # Submission.
    ('', include('mkt.submit.urls')),
    # Launchpad.
    url('^$', views.index, name='hub.index'),
))
