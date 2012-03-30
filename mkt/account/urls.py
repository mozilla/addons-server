from django.conf.urls.defaults import include, patterns, url

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
)


urlpatterns = decorate(login_required, patterns('',
    url('^settings$', views.account_settings, name='account.settings'),
    ('^settings/', include(settings_patterns)),
    url('^purchases/$', views.purchases, name='account.purchases'),
    url(r'^purchases/(?P<product_id>\d+)', views.purchases,
        name='account.purchases.receipt'),

    # Keeping the same URL pattern since admin pages already know about this.
    url(r'^user/(?:/(?P<user_id>\d+)/)?edit$', views.admin_edit,
        name='users.admin_edit'),
))
