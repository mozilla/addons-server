from waffle.views import wafflejs

from django.conf.urls import include, patterns, url
from django.views.decorators.cache import never_cache

from . import views


services_patterns = patterns(
    '',
    url('^monitor(.json)?$', never_cache(views.monitor),
        name='amo.monitor'),
    url('^loaded$', never_cache(views.loaded), name='amo.loaded'),
    url('^csp/report$', views.cspreport, name='amo.csp.report'),
)

urlpatterns = patterns(
    '',
    url('^robots.txt$', views.robots, name='robots.txt'),
    url('^contribute.json$', views.contribute, name='contribute.json'),
    url(r'^wafflejs$', wafflejs, name='wafflejs'),
    ('^services/', include(services_patterns)),
    url('^__version__$', views.version, name='version.json'),

    url('^opensearch.xml$', 'olympia.legacy_api.views.render_xml',
                            {'template': 'amo/opensearch.xml'},
                            name='amo.opensearch'),

)
