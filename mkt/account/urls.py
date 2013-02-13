from django.conf.urls import include, patterns, url
from django.shortcuts import redirect

from lib.misc.urlconf_decorator import decorate

from amo.decorators import login_required
from . import views


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
    ('^/', include(settings_patterns)),
)) + patterns('',
    url('^$', views.account_settings, name='account.settings'),
    url('^/feedback$', lambda r: redirect('site.feedback', permanent=True)),
)

purchases_patterns = decorate(login_required, patterns('',
    url(r'^(?P<product_id>\d+)', views.purchases,
        name='account.purchases.receipt'),
)) + patterns('',
    url('^$', views.purchases, name='account.purchases'),
)

users_patterns = patterns('',
    # Keeping the same URL pattern since admin pages already know about this.
    url(r'^(?:(?P<user_id>\d+)/)?edit$', views.admin_edit,
        name='users.admin_edit'),
    url(r'''^(?P<username>[^/<>"']+)$''', views.profile,
        name='users.profile'),
    url(r'''^(?P<username>[^/<>"']+)/abuse$''', views.abuse,
        name='users.abuse')
)
