from django.conf.urls.defaults import include, patterns, url
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect

from session_csrf import anonymous_csrf
from lib.misc.urlconf_decorator import decorate

from amo.decorators import login_required
from users.forms import PasswordResetForm
from users.models import UserProfile
from . import views


# We need Django to use our User model.
auth_views.User = UserProfile


settings_patterns = patterns('',
    url('delete$', views.delete, name='account.delete'),
    url('delete_photo$', views.delete_photo,
        name='account.delete_photo'),
    url('payment(?:/(?P<status>cancel|complete|remove))?$', views.payment,
        name='account.payment'),
    url('payment/preapproval$', views.preapproval,
        name='account.payment.preapproval'),
    url('payment/currency$', views.currency,
        name='account.payment.currency'),
)


# Require authentication.
settings_patterns = decorate(login_required, patterns('',
    url('^$', views.account_settings, name='account.settings'),
    ('^/', include(settings_patterns)),
))

purchases_patterns = decorate(login_required, patterns('',
    url('^$', views.purchases, name='account.purchases'),
    url(r'^(?P<product_id>\d+)', views.purchases,
        name='account.purchases.receipt'),
))

users_patterns = patterns('',
    url(r'^register$', lambda r: redirect('users.login', permanent=True)),

    url(r'^pwreset/?$', anonymous_csrf(auth_views.password_reset),
        {'template_name': 'account/pwreset/request.html',
         'email_template_name': 'users/email/pwreset.ltxt',
         'password_reset_form': PasswordResetForm}, name='users.pwreset'),
    url(r'^pwreset/(?P<uidb36>\w{1,13})/(?P<token>\w{1,13}-\w{1,20})$',
        views.password_reset_confirm, name='users.pwreset_confirm'),
    url(r'^pwresetsent$', auth_views.password_reset_done,
        {'template_name': 'account/pwreset/sent.html'},
        name='users.pwreset_sent'),
    url(r'^pwresetcomplete$', auth_views.password_reset_complete,
        {'template_name': 'account/pwreset/complete.html'},
        name='users.pwreset_complete'),

    # Keeping the same URL pattern since admin pages already know about this.
    url(r'^(?:(?P<user_id>\d+)/)?edit$', views.admin_edit,
        name='users.admin_edit'),
    url(r'''(?P<username>[^/<>"']+)$''', views.profile,
        name='users.profile'),
)
