from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from .views import (
    AddonReviewerViewSet, ReviewAddonVersionViewSet)


addons = SimpleRouter()
addons.register(r'addon', AddonReviewerViewSet, basename='reviewers-addon')

versions = NestedSimpleRouter(addons, r'addon', lookup='addon')
versions.register(
    r'versions', ReviewAddonVersionViewSet, basename='reviewers-versions')


urlpatterns = [
    url(r'', include(addons.urls)),
    url(r'', include(versions.urls)),
]
