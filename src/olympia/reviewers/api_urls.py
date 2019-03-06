from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from .views import (
    AddonReviewerViewSet, ReviewAddonVersionViewSet,
    ReviewAddonVersionCompareViewSet)


addons = SimpleRouter()
addons.register(r'addon', AddonReviewerViewSet, basename='reviewers-addon')

versions = NestedSimpleRouter(addons, r'addon', lookup='addon')
versions.register(
    r'versions', ReviewAddonVersionViewSet, basename='reviewers-versions')

compare = NestedSimpleRouter(versions, r'versions', lookup='version')
compare.register(
    r'compare_to', ReviewAddonVersionCompareViewSet,
    basename='reviewers-versions-compare')


urlpatterns = [
    url(r'', include(addons.urls)),
    url(r'', include(versions.urls)),
    url(r'', include(compare.urls))
]
