from django.conf.urls.defaults import patterns, url

from jingo.views import direct_to_template

from . import views


urlpatterns = patterns('',
    url('^about$', direct_to_template, {'template': 'pages/about.lhtml'},
        name='pages.about'),
    url('^faq$', direct_to_template, {'template': 'pages/faq.lhtml'},
        name='pages.faq'),
)
