from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url(r'purchases/$', views.purchases, name='account.purchases'),
    url(r'purchases/(?P<product_id>\d+)', views.purchases,
        name='account.purchases.receipt'),
)
