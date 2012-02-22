from django.conf.urls.defaults import patterns, url

from jingo.views import direct_to_template


urlpatterns = patterns('',
    url('^privacy-policy$', direct_to_template,
        {'template': 'site/privacy-policy.html'}, name='site.privacy'),
    url('^terms-of-use$', direct_to_template,
        {'template': 'site/terms-of-use.html'}, name='site.terms'),
)
