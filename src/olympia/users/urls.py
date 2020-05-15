from django.conf.urls import include, url

from olympia.amo.views import frontend_view


USER_ID = r"""(?P<user_id>[^/<>"']+)"""


# These will all start with /user/<user_id>/
detail_patterns = [
    url(r'^$', frontend_view, name='users.profile'),
    url(r'^themes(?:/(?P<category>[^ /]+))?$', frontend_view,
        name='users.themes'),
    url(r'^edit$', frontend_view, name='users.admin_edit'),
]

users_patterns = [
    url(r'^edit$', frontend_view, name='users.edit'),
    url(r'^unsubscribe/(?P<token>[-\w]+={0,3})/(?P<hash>[\w]+)/'
        r'(?P<perm_setting>[\w]+)?$', frontend_view,
        name='users.unsubscribe'),
]

urlpatterns = [
    # URLs for a single user.
    url(r'^user/%s/' % USER_ID, include(detail_patterns)),
    url(r'^users/', include(users_patterns)),
]
