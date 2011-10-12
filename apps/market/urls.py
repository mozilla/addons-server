from django.conf.urls.defaults import patterns, url

from addons.urls import ADDON_ID
from market import views


urlpatterns = patterns('',
    url(r'^verify/%s$' % ADDON_ID, views.verify_receipt,
        name='api.market.verify'),
    url(r'^urls$', views.get_manifest_urls, name='api.market.urls'),
)
