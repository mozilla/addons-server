from django.conf.urls.defaults import patterns, url, include

from . import views

# These will all start with /user/<user_id>/
detail_patterns = patterns('',
    url('^$', views.profile, name='users.profile'),
)


urlpatterns = patterns('',
    # URLs for a single user.
    ('^user/(?P<user_id>\d+)/', include(detail_patterns)),

    url('^users/logout$', views.logout_view, name='users.logout'),
)
