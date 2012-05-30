from django.conf.urls.defaults import patterns, url, include

from . import views


# These views all start with user ID.
detail_patterns = patterns('',
    url(r'^summary$', views.summary, name='acct_lookup.summary'),
)


urlpatterns = patterns('',
    url(r'^$', views.home, name='acct_lookup.home'),
    url(r'^search\.json$', views.search, name='acct_lookup.search'),
    (r'''^(?P<user_id>[^/<>"']+)/''', include(detail_patterns)),
)
