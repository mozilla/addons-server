from django.conf.urls.defaults import patterns, url, include

from . import views


detail_urls = patterns('',
    url('^$', views.collection_detail, name='collections.detail'),
    url('^vote/(?P<direction>up|down)$', views.collection_vote,
        name='collections.vote'),
)


urlpatterns = patterns('',
    url('^collection/(?P<uuid>[^/]+)/?$', views.legacy_redirect),

    url('^collections/$', views.collection_listing, name='collections.list'),
    url('^collections/(?P<username>[^/]+)/$', views.user_listing,
        name='collections.user'),
    url('^collections/(?P<username>[^/]+)/(?P<slug>[^/]+)/',
        include(detail_urls)),
    url('^collections/add$', views.add, name='collections.add'),
)
