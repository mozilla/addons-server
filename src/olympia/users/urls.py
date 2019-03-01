from django.conf.urls import include, url

from . import views


USER_ID = r"""(?P<user_id>[^/<>"']+)"""


# These will all start with /user/<user_id>/
detail_patterns = [
    url(r'^$', views.profile, name='users.profile'),
    url(r'^themes(?:/(?P<category>[^ /]+))?$', views.themes,
        name='users.themes'),
    url(r'^abuse', views.report_abuse, name='users.abuse'),
    url(r'^edit$', views.admin_edit, name='users.admin_edit'),
]

users_patterns = [
    url(r'^ajax$', views.ajax, name='users.ajax'),
    url(r'^delete$', views.delete, name='users.delete'),
    url(r'^delete_photo/(?P<user_id>\d+)?$', views.delete_photo,
        name='users.delete_photo'),
    url(r'^edit$', views.edit, name='users.edit'),
    url(r'^unsubscribe/(?P<token>[-\w]+={0,3})/(?P<hash>[\w]+)/'
        r'(?P<perm_setting>[\w]+)?$', views.unsubscribe,
        name="users.unsubscribe"),
]


urlpatterns = [
    # URLs for a single user.
    url(r'^user/%s/' % USER_ID, include(detail_patterns)),
    url(r'^users/', include(users_patterns)),
]
