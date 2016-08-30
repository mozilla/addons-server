from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from olympia.reviews.views import ReviewViewSet

from .views import (
    AddonFeaturedView, AddonSearchView, AddonVersionViewSet, AddonViewSet)

addons = SimpleRouter()
addons.register(r'addon', AddonViewSet)

# Router for children of /addons/addon/{addon_pk}/.
sub_addons = NestedSimpleRouter(addons, r'addon', lookup='addon')
sub_addons.register('versions', AddonVersionViewSet, base_name='addon-version')
sub_addons.register('reviews', ReviewViewSet, base_name='addon-review')

urlpatterns = patterns(
    '',

    url(r'', include(addons.urls)),
    url(r'', include(sub_addons.urls)),
    url(r'^search/$', AddonSearchView.as_view(), name='addon-search'),
    url(r'^featured/$', AddonFeaturedView.as_view(), name='addon-featured'),
)
