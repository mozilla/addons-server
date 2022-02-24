from django.urls import include, path, re_path
from django.views.generic.base import TemplateView

from . import views

services_patterns = [
    re_path(r'^monitor\.json$', views.heartbeat, name='amo.monitor'),
    re_path(r'^client_info', views.client_info, name='amo.client_info'),
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
    re_path(r'^__heartbeat__$', views.heartbeat, name='amo.heartbeat'),
    re_path(
        r'^opensearch\.xml$',
        TemplateView.as_view(
            template_name='amo/opensearch.xml', content_type='text/xml'
        ),
        name='amo.opensearch',
    ),
    re_path(
        r'^fake-fxa-authorization/$',
        views.fake_fxa_authorization,
        name='fake-fxa-authorization',
    ),
    path('sitemap.xml', views.sitemap, name='amo.sitemap'),
]
