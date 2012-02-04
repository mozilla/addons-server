from django.conf.urls.defaults import patterns, url

from . import views

from jingo.views import direct_to_template

APP_SLUG = r"""(?P<app_slug>[^/<>"']+)"""

urlpatterns = patterns('',
    url('^$', direct_to_template,
        {'template': 'marketplace-experiments/base.html'},
        name='mrkt.index'),
    url('^app/%s/' % APP_SLUG, views.detail, name='mkt.detail'),
)