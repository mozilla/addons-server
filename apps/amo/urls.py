from django.conf.urls.defaults import patterns, url, include

from . import views

services_patterns = patterns('',
    url('^monitor$', views.monitor, name='amo.monitor'),
    url('^paypal$', views.paypal, name='amo.paypal'),
    url('^loaded$', views.loaded, name='amo.loaded'),
)

urlpatterns = patterns('',
    ('^services/', include(services_patterns)),

    url('^opensearch.xml$', 'api.views.render_xml',
                            {'template': 'amo/opensearch.xml'},
                            name='amo.opensearch'),

)
