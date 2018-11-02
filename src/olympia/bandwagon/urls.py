from django.conf.urls import include, url

from . import views


edit_urls = [
    url(r'^$', views.edit, name='collections.edit'),
    url(r'^addons$', views.edit_addons, name='collections.edit_addons'),
    url(r'^privacy$', views.edit_privacy, name='collections.edit_privacy'),
]

detail_urls = [
    url(r'^$', views.collection_detail, name='collections.detail'),
    url(r'^format:json$', views.collection_detail_json,
        name='collections.detail.json'),
    url(r'^edit/', include(edit_urls)),
    url(r'^delete$', views.delete, name='collections.delete'),
    url(r'^delete_icon$', views.delete_icon, name='collections.delete_icon'),
    url(r'^(?P<action>add|remove)$', views.collection_alter,
        name='collections.alter'),
]

ajax_urls = [
    url(r'^list$', views.ajax_list, name='collections.ajax_list'),
    url(r'^add$', views.ajax_collection_alter, {'action': 'add'},
        name='collections.ajax_add'),
    url(r'^remove$', views.ajax_collection_alter, {'action': 'remove'},
        name='collections.ajax_remove'),
    url(r'^new$', views.ajax_new, name='collections.ajax_new'),
]

urlpatterns = [
    url(r'^collection/(?P<uuid>[^/]+)/?$', views.legacy_redirect),
    url(r'^collections/view/(?P<uuid>[^/]+)/?$', views.legacy_redirect),
    url(r'^collections/edit/(?P<uuid>[^/]+)/?$', views.legacy_redirect,
        {'edit': True}),

    url(r'^collections/$', views.collection_listing, name='collections.list'),

    url(r'^collections/(editors_picks|popular|favorites)/?$',
        views.legacy_directory_redirects),
    url(r'^collections/mine/(?P<slug>[^/]+)?$', views.mine,
        name='collections.mine', kwargs={'username': 'mine'}),
    url(r'^collections/(?P<username>[^/]+)/$', views.user_listing,
        name='collections.user'),
    url(r'^collections/(?P<username>[^/]+)/(?P<slug>[^/]+)/',
        include(detail_urls)),
    url(r'^collections/add$', views.add, name='collections.add'),
    url(r'^collections/ajax/', include(ajax_urls)),
]
