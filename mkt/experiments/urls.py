from django.conf.urls.defaults import patterns, url

from . import views

from jingo.views import direct_to_template

APP_SLUG = r"""(?P<app_slug>[^/<>"']+)"""

urlpatterns = patterns('',
    url('^$', views.detail, name='mkt.experiments'),
)
