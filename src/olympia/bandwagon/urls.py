from django.conf.urls import include, url

from olympia.stats.urls import collection_stats_urls

from . import views


edit_urls = [
    url('^$', views.edit, name='collections.edit'),
    url('^addons$', views.edit_addons, name='collections.edit_addons'),
    url('^privacy$', views.edit_privacy, name='collections.edit_privacy'),
]

detail_urls = [
    url('^$', views.collection_detail, name='collections.detail'),
    url('^format:json$', views.collection_detail_json,
        name='collections.detail.json'),
    url('^vote/(?P<direction>up|down)$', views.collection_vote,
        name='collections.vote'),
    url('^edit/', include(edit_urls)),
    url('^delete$', views.delete, name='collections.delete'),
    url('^delete_icon$', views.delete_icon, name='collections.delete_icon'),
    url('^(?P<action>add|remove)$', views.collection_alter,
        name='collections.alter'),
    url('^watch$', views.watch, name='collections.watch'),
]

ajax_urls = [
    url('^list$', views.ajax_list, name='collections.ajax_list'),
    url('^add$', views.ajax_collection_alter, {'action': 'add'},
        name='collections.ajax_add'),
    url('^remove$', views.ajax_collection_alter, {'action': 'remove'},
        name='collections.ajax_remove'),
    url('^new$', views.ajax_new, name='collections.ajax_new'),
]

urlpatterns = [
    url('^collection/(?P<uuid>[^/]+)/?$', views.legacy_redirect),
    url('^collections/view/(?P<uuid>[^/]+)/?$', views.legacy_redirect),
    url('^collections/edit/(?P<uuid>[^/]+)/?$', views.legacy_redirect,
        {'edit': True}),

    url('^collections/$', views.collection_listing, name='collections.list'),

    url('^collections/(editors_picks|popular|favorites)/?$',
        views.legacy_directory_redirects),
    url('^collections/mine/(?P<slug>[^/]+)?$', views.mine,
        name='collections.mine', kwargs={'username': 'mine'}),
    url('^collections/following/', views.following,
        name='collections.following'),
    url('^collections/(?P<username>[^/]+)/$', views.user_listing,
        name='collections.user'),
    url('^collections/(?P<username>[^/]+)/(?P<slug>[^/]+)/',
        include(detail_urls)),
    url('^collections/(?P<username>[^/]+)/(?P<slug>[^/]+)/statistics/',
        include(collection_stats_urls)),
    url('^collections/add$', views.add, name='collections.add'),
    url('^collections/ajax/', include(ajax_urls)),
]
