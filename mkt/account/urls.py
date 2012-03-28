from django.conf.urls.defaults import patterns, url

from lib.misc.urlconf_decorator import decorate

from amo.decorators import login_required
from . import views


urlpatterns = decorate(login_required, patterns('',
    url('purchases/$', views.purchases, name='account.purchases'),
    url(r'purchases/(?P<product_id>\d+)', views.purchases,
        name='account.purchases.receipt'),
    url('settings/$', views.account_settings, name='account.settings'),
    url('settings/delete$', views.delete, name='account.delete'),
    url('settings/delete_photo$', views.delete_photo,
        name='account.delete_photo'),

    # Keeping the same URL pattern since admin pages already know about this.
    url(r'user/(?:/(?P<user_id>\d+)/)?edit$', views.admin_edit,
        name='users.admin_edit'),
))
