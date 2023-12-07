from django.urls import include, re_path

from olympia.amo.views import frontend_view

from . import views


USER_ID = r"""(?P<user_id>[^/<>"']+)"""

# These will all start with /user/<user_id>/
detail_patterns = [
    re_path(r'^$', frontend_view, name='users.profile'),
    re_path(r'^edit$', frontend_view, name='users.admin_edit'),
]

users_patterns = [
    re_path(r'^edit$', frontend_view, name='users.edit'),
    re_path(
        r'^unsubscribe/(?P<token>[-\w]+={0,3})/(?P<hash>[\w]+)/'
        r'(?P<perm_setting>[\w]+)?$',
        frontend_view,
        name='users.unsubscribe',
    ),
]

email_suppression_patterns = [
    re_path(
        r'^$',
        views.SuppressedEmailDetailView.as_view(),
        name='users.suppressedemails',
    ),
]

urlpatterns = [
    # URLs for a single user.
    re_path(r'^user/%s/' % USER_ID, include(detail_patterns)),
    re_path(r'^users/', include(users_patterns)),
    # URLs for email suppression.
    re_path(r'^suppressed_emails/', include(email_suppression_patterns)),
]
