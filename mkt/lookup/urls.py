from django.conf.urls import include, patterns, url

from . import views


# These views all start with user ID.
user_patterns = patterns('',
    url(r'^summary$', views.user_summary, name='lookup.user_summary'),
    url(r'^purchases$', views.user_purchases,
        name='lookup.user_purchases'),
    url(r'^activity$', views.user_activity, name='lookup.user_activity'),
)


# These views all start with app/addon ID.
app_patterns = patterns('',
    url(r'^summary$', views.app_summary, name='lookup.app_summary'),
)


urlpatterns = patterns('',
    url(r'^$', views.home, name='lookup.home'),
    url(r'^user_search\.json$', views.user_search,
        name='lookup.user_search'),
    url(r'^app_search\.json$', views.app_search,
        name='lookup.app_search'),
    (r'^app/(?P<addon_id>[^/]+)/', include(app_patterns)),
    (r'^user/(?P<user_id>[^/]+)/', include(user_patterns)),
)
