from django.conf.urls import patterns, url

from jingo.views import direct_to_template

from . import views


urlpatterns = patterns('',
    url('^mozmarket.js$', views.mozmarket_js, name='site.mozmarket_js'),
    url('^privacy-policy$', direct_to_template,
        {'template': 'site/privacy-policy.html'}, name='site.privacy'),
    url('^terms-of-use$', direct_to_template,
        {'template': 'site/terms-of-use.html'}, name='site.terms'),
    url('^robots.txt$', views.robots, name='robots.txt'),
    url('^manifest.webapp$', views.manifest, name='manifest.webapp'),
    url('^csrf$', views.csrf, name='csrf'),
    url('^timing/record$', views.record, name='mkt.timing.record'),
)
