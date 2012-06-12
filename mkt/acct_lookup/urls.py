from django.conf.urls.defaults import patterns, url, include

from . import views


# These views all start with user ID.
user_patterns = patterns('',
    url(r'^summary$', views.user_summary, name='acct_lookup.user_summary'),
    url(r'^purchases$', views.user_purchases,
        name='acct_lookup.user_purchases'),
    url(r'^activity$', views.activity, name='acct_lookup.user_activity'),
)


# These views all start with app slug.
app_patterns = patterns('',
    url(r'^summary$', views.app_summary, name='acct_lookup.app_summary'),
)


urlpatterns = patterns('',
    url(r'^$', views.home, name='acct_lookup.home'),
    url(r'^user_search\.json$', views.user_search,
        name='acct_lookup.user_search'),
    url(r'^app_search\.json$', views.app_search,
        name='acct_lookup.app_search'),
    (r'^app/(?P<app_slug>[^/]+)/', include(app_patterns)),
    (r'^user/(?P<user_id>[^/]+)/', include(user_patterns)),
)
