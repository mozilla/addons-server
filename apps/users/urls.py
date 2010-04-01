from django.conf.urls.defaults import patterns, url, include

from . import auth_views
from . import forms
from . import views

# These will all start with /user/<user_id>/
detail_patterns = patterns('',
    url('^$', views.profile, name='users.profile'),
    url('^confirm/resend$', views.confirm_resend, name='users.confirm.resend'),
    url('^confirm/(?P<token>[-\w]+)$', views.confirm, name='users.confirm'),
    url(r'^emailchange/(?P<token>[-\w]+={0,3})/(?P<hash>[\w]+)$',
                        views.emailchange, name="users.emailchange"),
)

urlpatterns = patterns('',
    # URLs for a single user.
    ('^user/(?P<user_id>\d+)/', include(detail_patterns)),

    url('^users/delete$', views.delete, name='users.delete'),
    url('^users/edit$', views.edit, name='users.edit'),
    url('^users/login', views.login, name='users.login'),
    url('^users/logout', views.logout, name='users.logout'),
    url('^users/register$', views.register, name='users.register'),

    # Password reset stuff
    url(r'^users/pwreset/?$', auth_views.password_reset,
                            {'template_name': 'users/pwreset_request.html',
                             'email_template_name': 'users/email/pwreset.ltxt',
                             'password_reset_form': forms.PasswordResetForm,
                            },
                            name="users.pwreset"),
    url(r'^users/pwresetsent$', auth_views.password_reset_done,
                            {'template_name': 'users/pwreset_sent.html'}),
    url(r'^users/pwreset/(?P<uidb36>[-\w]+)/(?P<token>[-\w]+)$',
                            auth_views.password_reset_confirm,
                            {'template_name': 'users/pwreset_confirm.html',
                             'set_password_form': forms.SetPasswordForm,
                            }),
    url(r'^users/pwresetcomplete$', auth_views.password_reset_complete,
                            {'template_name': 'users/pwreset_complete.html'}),
)
