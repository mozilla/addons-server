from django.conf.urls.defaults import patterns, url, include

from . import views, feeds

edit_urls = patterns('',
    url('^$', views.edit, name='collections.edit'),
    url('^addons$', views.edit_addons, name='collections.edit_addons'),
    url('^privacy$', views.edit_privacy, name='collections.edit_privacy'),
    url('^contributors$', views.edit_contributors,
        name='collections.edit_contributors'),
)

detail_urls = patterns('',
    url('^$', views.collection_detail, name='collections.detail'),
    url('^vote/(?P<direction>up|down)$', views.collection_vote,
        name='collections.vote'),
    url('^edit/', include(edit_urls)),
    url('^delete$', views.delete, name='collections.delete'),
    url('^delete_icon$', views.delete_icon, name='collections.delete_icon'),
    url('^(?P<action>add|remove)$', views.collection_alter,
        name='collections.alter'),
    url('^watch$', views.watch, name='collections.watch'),
    url('^share$', views.share, name='collections.share'),
    url('^format:rss$', feeds.CollectionFeed(),
        name='collections.detail.rss'),
)

ajax_urls = patterns('',
    url('^list$', views.ajax_list, name='collections.ajax_list'),
    url('^add$', views.ajax_collection_alter, {'action': 'add'},
        name='collections.ajax_add'),
    url('^remove$', views.ajax_collection_alter, {'action': 'remove'},
        name='collections.ajax_remove'),
    url('^new$', views.ajax_new, name='collections.ajax_new'),
)

urlpatterns = patterns('',
    url('^collection/(?P<uuid>[^/]+)/?$', views.legacy_redirect),
    url('^collections/view/(?P<uuid>[^/]+)/?$', views.legacy_redirect),

    url('^collections/$', views.collection_listing, name='collections.list'),
    url('^collections/(editors_picks|popular|mine|favorites)/?$',
        views.legacy_directory_redirects),
    url('^collections/following/', views.following,
        name='collections.following'),
    url('^collections/(?P<username>[^/]+)/$', views.user_listing,
        name='collections.user'),
    url('^collections/(?P<username>[^/]+)/(?P<slug>[^/]+)/',
        include(detail_urls)),
    url('^collections/add$', views.add, name='collections.add'),
    url('^collections/ajax/', include(ajax_urls)),
)
