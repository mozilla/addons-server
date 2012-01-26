from django.conf.urls.defaults import patterns, url

from jingo.views import direct_to_template


urlpatterns = patterns('',
    url('^about$', direct_to_template, {'template': 'pages/about.lhtml'},
        name='pages.about'),
    url('^faq$', direct_to_template, {'template': 'pages/faq.html'},
        name='pages.faq'),
    url('^compatibility_firstrun$', direct_to_template,
        {'template': 'pages/acr_firstrun.html'}, name='pages.acr_firstrun'),
    url('^developer_faq$', direct_to_template,
        {'template': 'pages/dev_faq.html'}, name='pages.dev_faq'),
)
