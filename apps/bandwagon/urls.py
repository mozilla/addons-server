from django.conf.urls.defaults import patterns, url, include

from . import views

edit_urls = patterns('',
    url('^$', views.edit, name='collections.edit'),
    url('^addons$', views.edit_addons, name='collections.edit_addons'),
    url('^contributors$', views.edit_contributors,
        name='collections.edit_contributors'),
)

detail_urls = patterns('',
    url('^$', views.collection_detail, name='collections.detail'),
    url('^vote/(?P<direction>up|down)$', views.collection_vote,
        name='collections.vote'),
    url('^edit/', include(edit_urls)),
    url('^delete$', views.delete, name='collections.delete'),
    url('^(?P<action>add|remove)$', views.collection_alter,
        name='collections.alter'),
)

ajax_urls = patterns('',
    url('^list$', views.ajax_list, name='collections.ajax_list'),
    url('^add$', views.ajax_add, name='collections.ajax_add'),
    url('^remove$', views.ajax_remove, name='collections.ajax_remove'),
    url('^new$', views.ajax_new, name='collections.ajax_new'),
)

urlpatterns = patterns('',
    url('^collection/(?P<uuid>[^/]+)/?$', views.legacy_redirect),

    url('^collections/$', views.collection_listing, name='collections.list'),
    url('^collections/(editors_picks|popular|mine|favorites)/?$',
        views.legacy_directory_redirects),
    url('^collections/(?P<username>[^/]+)/$', views.user_listing,
        name='collections.user'),
    url('^collections/(?P<username>[^/]+)/(?P<slug>[^/]+)/',
        include(detail_urls)),
    url('^collections/add$', views.add, name='collections.add'),
    url('^collections/ajax/', include(ajax_urls)),
)
