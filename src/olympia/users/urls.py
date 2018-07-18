from django.conf.urls import include, url
from django.views.generic.base import RedirectView

from . import views


USER_ID = r"""(?P<user_id>[^/<>"']+)"""


# These will all start with /user/<user_id>/
detail_patterns = [
    url('^$', views.profile, name='users.profile'),
    url(
        '^themes(?:/(?P<category>[^ /]+))?$', views.themes, name='users.themes'
    ),
    url('^abuse', views.report_abuse, name='users.abuse'),
]

users_patterns = [
    url('^ajax$', views.ajax, name='users.ajax'),
    url('^delete$', views.delete, name='users.delete'),
    url(
        '^delete_photo/(?P<user_id>\d+)?$',
        views.delete_photo,
        name='users.delete_photo',
    ),
    url('^edit$', views.edit, name='users.edit'),
    url(
        '^edit(?:/(?P<user_id>\d+))?$',
        views.admin_edit,
        name='users.admin_edit',
    ),
    url('^login', views.login, name='users.login'),
    url('^logout', views.logout, name='users.logout'),
    url(
        '^register$',
        RedirectView.as_view(pattern_name='users.login', permanent=True),
        name='users.register',
    ),
    url(
        r'^unsubscribe/(?P<token>[-\w]+={0,3})/(?P<hash>[\w]+)/'
        r'(?P<perm_setting>[\w]+)?$',
        views.unsubscribe,
        name="users.unsubscribe",
    ),
]


urlpatterns = [
    # URLs for a single user.
    url('^user/%s/' % USER_ID, include(detail_patterns)),
    url('^users/', include(users_patterns)),
]
