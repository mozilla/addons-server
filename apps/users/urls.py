from django.contrib.auth import views as auth_views
from django.conf.urls import include, patterns, url

from session_csrf import anonymous_csrf

from . import forms, views
from .models import UserProfile


# We need Django to use our User model.
auth_views.User = UserProfile


# These will all start with /user/<user_id>/
detail_patterns = patterns('',
    url('^$', views.profile, name='users.profile'),
    url('^confirm/resend$', views.confirm_resend, name='users.confirm.resend'),
    url('^confirm/(?P<token>[-\w]+)$', views.confirm, name='users.confirm'),
    url(r'^emailchange/(?P<token>[-\w]+={0,3})/(?P<hash>[\w]+)$',
                        views.emailchange, name="users.emailchange"),
    url('^abuse', views.report_abuse, name='users.abuse'),
)


users_patterns = patterns('',
    url('^ajax$', views.ajax, name='users.ajax'),
    url('^delete$', views.delete, name='users.delete'),
    url('^delete_photo$', views.delete_photo, name='users.delete_photo'),
    url('^edit$', views.edit, name='users.edit'),
    url('^edit(?:/(?P<user_id>\d+))?$', views.admin_edit,
        name='users.admin_edit'),
    url('^browserid-login', views.browserid_login,
        name='users.browserid_login'),
    url('^login/modal', views.login_modal, name='users.login_modal'),
    url('^login', views.login, name='users.login'),
    url('^logout', views.logout, name='users.logout'),
    url('^register$', views.register, name='users.register'),
    url(r'^pwreset/?$', anonymous_csrf(auth_views.password_reset),
                        {'template_name': 'users/pwreset_request.html',
                         'email_template_name': 'users/email/pwreset.ltxt',
                         'password_reset_form': forms.PasswordResetForm,
                        }, name="users.pwreset"),
    url(r'^pwresetsent$', auth_views.password_reset_done,
                        {'template_name': 'users/pwreset_sent.html'},
                        name="users.pwreset_sent"),
    url(r'^pwreset/(?P<uidb36>\w{1,13})/(?P<token>\w{1,13}-\w{1,20})$',
                        views.password_reset_confirm,
                        name="users.pwreset_confirm"),
    url(r'^pwresetcomplete$', auth_views.password_reset_complete,
                        {'template_name': 'users/pwreset_complete.html'},
                        name="users.pwreset_complete"),
    url(r'^unsubscribe/(?P<token>[-\w]+={0,3})/(?P<hash>[\w]+)/'
         '(?P<perm_setting>[\w]+)?$', views.unsubscribe,
        name="users.unsubscribe"),
    url(r'purchases/$', views.purchases, name='users.purchases'),
    url(r'purchases/(?P<addon_id>\d+)', views.purchases,
        name='users.purchases.receipt'),
    url(r'support/(?P<contribution_id>\d+)(?:/(?P<step>[\w-]+))?$',
        views.SupportWizard.as_view(),
        name='users.support'),
    url(r'payments(?:/(?P<status>cancel|complete|remove))?$', views.payments,
        name='users.payments'),
    url(r'payments/preapproval$', views.preapproval,
        name='users.payments.preapproval'),
)


urlpatterns = patterns('',
    # URLs for a single user.
    ('^user/(?P<user_id>\d+)/', include(detail_patterns)),
    ('^users/', include(users_patterns)),
)
