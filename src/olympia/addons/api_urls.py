from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from olympia.activity.views import VersionReviewNotesViewSet

from .views import (
    AddonFeaturedView, AddonSearchView, AddonVersionViewSet, AddonViewSet,
    StaticCategoryView)


addons = SimpleRouter()
addons.register(r'addon', AddonViewSet, base_name='addon')

# Router for children of /addons/addon/{addon_pk}/.
sub_addons = NestedSimpleRouter(addons, r'addon', lookup='addon')
sub_addons.register('versions', AddonVersionViewSet, base_name='addon-version')
sub_versions = NestedSimpleRouter(sub_addons, r'versions', lookup='version')
sub_versions.register(r'reviewnotes', VersionReviewNotesViewSet,
                      base_name='version-reviewnotes')

urlpatterns = [
    url(r'', include(addons.urls)),
    url(r'', include(sub_addons.urls)),
    url(r'', include(sub_versions.urls)),
    url(r'^search/$', AddonSearchView.as_view(), name='addon-search'),
    url(r'^featured/$', AddonFeaturedView.as_view(), name='addon-featured'),
    url(r'^categories/$', StaticCategoryView.as_view(), name='category-list'),
]
