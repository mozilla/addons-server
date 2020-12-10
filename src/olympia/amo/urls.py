from django.urls import include, re_path
from django.views.decorators.cache import never_cache

from . import views
from .utils import render_xml


services_patterns = [
    re_path(r'^monitor\.json$', never_cache(views.monitor), name='amo.monitor'),
    re_path(r'^loaded$', never_cache(views.loaded), name='amo.loaded'),
    re_path(r'^403', views.handler403),
    re_path(r'^404', views.handler404),
    re_path(r'^500', views.handler500),
]

api_patterns = [
    re_path(r'^site/$', views.SiteStatusView.as_view(), name='amo-site-status'),
]

urlpatterns = [
    re_path(r'^robots\.txt$', views.robots, name='robots.txt'),
    re_path(r'^contribute\.json$', views.contribute, name='contribute.json'),
    re_path(r'^services/', include(services_patterns)),
    re_path(r'^__version__$', views.version, name='version.json'),
    re_path(
        r'^opensearch\.xml$',
        render_xml,
        {'template': 'amo/opensearch.xml'},
        name='amo.opensearch',
    ),
    re_path(
        r'^fake-fxa-authorization/$',
        views.fake_fxa_authorization,
        name='fake-fxa-authorization',
    ),
]
