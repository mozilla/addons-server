from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^collection/(?P<uuid>[^/]+)/?$', views.legacy_redirect),

    url('^collections/$', views.collection_listing, name='collections.list'),
    url('^collections/(?P<user>[^/]+)/$', views.user_listing,
        name='collections.user'),
    url('^collections/(?P<user>[^/]+)/(?P<slug>[^/]+)$',
        views.collection_detail, name='collections.detail'),
)
