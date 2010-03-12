from django.conf.urls.defaults import patterns, url, include

from . import auth_views
from . import forms
from . import views

# These will all start with /user/<user_id>/
detail_patterns = patterns('',
    url('^$', views.profile, name='users.profile'),
)


urlpatterns = patterns('',
    # URLs for a single user.
    ('^user/(?P<user_id>\d+)/', include(detail_patterns)),
    url('^users/edit$', views.user_edit, name='users.edit'),
    url('^users/logout$', views.logout_view, name='users.logout'),

    # Password reset stuff
    url(r'^users/pwreset/?$', auth_views.password_reset,
                            {'template_name': 'pwreset_request.html',
                             'email_template_name': 'email/pwreset.lhtml',
                             'password_reset_form': forms.PasswordResetForm,
                            }),
    url(r'^users/pwresetsent$', auth_views.password_reset_done,
                            {'template_name': 'pwreset_sent.html'}),
    url(r'^users/pwreset/(?P<uidb36>[-\w]+)/(?P<token>[-\w]+)$',
                            auth_views.password_reset_confirm,
                            {'template_name': 'pwreset_confirm.html',
                             'set_password_form': forms.SetPasswordForm,
                            }),
    url(r'^users/pwresetcomplete$', auth_views.password_reset_complete,
                            {'template_name': 'pwreset_complete.html'}),
)
