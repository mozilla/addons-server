from django.conf.urls.defaults import patterns, url

from . import views

urlpatterns = patterns('',
    url('^$', views.landing, name='ecosystem.landing'),
    url('^building$', views.building, name='ecosystem.building'),
    url('^partners$', views.partners, name='ecosystem.partners'),
    url('^support$', views.support, name='ecosystem.support'),
    url('^documentation/(?P<page>\w+)?$', views.documentation,
        name='ecosystem.documentation'),

    # This is temporarily hardcoded for now until MDN can support live
    # Javascript content and the information accessible through there.
    url('^building/xtags/(?P<xtag>\w+)$', views.building_xtag,
        name='ecosystem.building_xtag'),
)
