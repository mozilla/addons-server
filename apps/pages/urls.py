from django.conf.urls.defaults import patterns, url
from django.http import HttpResponsePermanentRedirect

from jingo.views import direct_to_template

from amo.urlresolvers import reverse

from . import views


urlpatterns = patterns('',
    url('^about$', direct_to_template, {'template': 'pages/about.lhtml'},
        name='pages.about'),
    url('^credits$', views.credits, name='pages.credits'),
    url('^faq$', direct_to_template, {'template': 'pages/faq.html'},
        name='pages.faq'),
    url('^(?:pages/)?compatibility_firstrun$', direct_to_template,
        {'template': 'pages/acr_firstrun.html'}, name='pages.acr_firstrun'),
    url('^developer_faq$', direct_to_template,
        {'template': 'pages/dev_faq.html'}, name='pages.dev_faq'),
    url('^review_guide$', direct_to_template,
        {'template': 'pages/review_guide.html'}, name='pages.review_guide'),
    url('^sunbird$', direct_to_template,
        {'template': 'pages/sunbird.html'}, name='pages.sunbird'),
    url('^sunbird/', lambda r: HttpResponsePermanentRedirect(reverse('pages.sunbird')),
	name='pages.sunbird_redirect'),
)
