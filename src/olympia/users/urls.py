from django.conf.urls import include, patterns, url
from django.contrib.auth import views as auth_views
from django.views.generic.base import RedirectView

from session_csrf import anonymous_csrf

from . import forms, views


USER_ID = r"""(?P<user_id>[^/<>"']+)"""


# These will all start with /user/<user_id>/
detail_patterns = patterns(
    '',
    url('^$', views.profile, name='users.profile'),
    url('^themes(?:/(?P<category>[^ /]+))?$', views.themes,
        name='users.themes'),
    url('^confirm/resend$', views.confirm_resend, name='users.confirm.resend'),
    url('^confirm/(?P<token>[-\w]+)$', views.confirm, name='users.confirm'),
    url(r'^emailchange/(?P<token>[-\w]+={0,3})/(?P<hash>[\w]+)$',
        views.emailchange, name="users.emailchange"),
    url('^abuse', views.report_abuse, name='users.abuse'),
    url('^rmlocale$', views.remove_locale, name='users.remove-locale'),
)


users_patterns = patterns(
    '',
    url('^ajax$', views.ajax, name='users.ajax'),
    url('^delete$', views.delete, name='users.delete'),
    url('^delete_photo/(?P<user_id>\d+)?$', views.delete_photo,
        name='users.delete_photo'),
    url('^edit$', views.edit, name='users.edit'),
    url('^edit(?:/(?P<user_id>\d+))?$', views.admin_edit,
        name='users.admin_edit'),
    url('^login/modal', views.login_modal, name='users.login_modal'),
    url('^login', views.login, name='users.login'),
    url('^logout', views.logout, name='users.logout'),
    url('^register$',
        RedirectView.as_view(pattern_name='users.login', permanent=True),
        name='users.register'),
    url('^migrate', views.migrate, name='users.migrate'),
    url(r'^pwreset/?$', anonymous_csrf(auth_views.password_reset),
        {'template_name': 'users/pwreset_request.html',
         'email_template_name': 'users/email/pwreset.ltxt',
         'password_reset_form': forms.PasswordResetForm},
        name='password_reset_form'),
    url(r'^pwresetsent$', auth_views.password_reset_done,
        {'template_name': 'users/pwreset_sent.html'},
        name="password_reset_done"),
    url(r'^pwreset/(?P<uidb64>[0-9A-Za-z_\-]+)/'
        r'(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})',
        views.password_reset_confirm,
        name="users.pwreset_confirm"),
    url(r'^pwresetcomplete$', auth_views.password_reset_complete,
        {'template_name': 'users/pwreset_complete.html'},
        name="users.pwreset_complete"),
    url(r'^unsubscribe/(?P<token>[-\w]+={0,3})/(?P<hash>[\w]+)/'
        r'(?P<perm_setting>[\w]+)?$', views.unsubscribe,
        name="users.unsubscribe"),
)


urlpatterns = patterns(
    '',
    # URLs for a single user.
    ('^user/%s/' % USER_ID, include(detail_patterns)),
    ('^users/', include(users_patterns)),
)
