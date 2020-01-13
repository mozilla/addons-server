from django.conf.urls import include, url
from django.views.decorators.cache import never_cache

from . import views
from .utils import render_xml


services_patterns = [
    url(r'^monitor\.json$', never_cache(views.monitor),
        name='amo.monitor'),
    url(r'^loaded$', never_cache(views.loaded), name='amo.loaded'),
    url(r'^403', views.handler403),
    url(r'^404', views.handler404),
    url(r'^500', views.handler500),
]

api_patterns = [
    url(r'^site/$', views.SiteStatusView.as_view(),
        name='amo-site-status'),
]

urlpatterns = [
    url(r'^robots\.txt$', views.robots, name='robots.txt'),
    url(r'^contribute\.json$', views.contribute, name='contribute.json'),
    url(r'^services/', include(services_patterns)),
    url(r'^__version__$', views.version, name='version.json'),
    url(r'^opensearch\.xml$', render_xml, {'template': 'amo/opensearch.xml'},
        name='amo.opensearch'),

]
