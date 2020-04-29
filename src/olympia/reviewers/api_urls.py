from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from .views import (
    AddonReviewerViewSet, ReviewAddonVersionViewSet,
    ReviewAddonVersionCompareViewSet, CannedResponseViewSet,
    ReviewAddonVersionDraftCommentViewSet, ReviewVersionFileViewSet,
    ReviewVersionFileCompareViewSet)


addons = SimpleRouter()
addons.register(r'addon', AddonReviewerViewSet, basename='reviewers-addon')

versions = NestedSimpleRouter(addons, r'addon', lookup='addon')
versions.register(
    r'versions', ReviewAddonVersionViewSet, basename='reviewers-versions')

files = NestedSimpleRouter(addons, r'addon', lookup='addon')
files.register(
    r'files', ReviewVersionFileViewSet, basename='reviewers-files')


compare = NestedSimpleRouter(versions, r'versions', lookup='version')
compare.register(
    r'compare_to', ReviewAddonVersionCompareViewSet,
    basename='reviewers-versions-compare')

compare_file = NestedSimpleRouter(versions, r'versions', lookup='version')
compare_file.register(
    r'compare_file', ReviewVersionFileCompareViewSet,
    basename='reviewers-compare-file')

draft_comments = NestedSimpleRouter(versions, r'versions', lookup='version')
draft_comments.register(
    r'draft_comments', ReviewAddonVersionDraftCommentViewSet,
    basename='reviewers-versions-draft-comment')

urlpatterns = [
    url(r'', include(addons.urls)),
    url(r'', include(versions.urls)),
    url(r'', include(files.urls)),
    url(r'', include(compare.urls)),
    url(r'', include(compare_file.urls)),
    url(r'', include(draft_comments.urls)),
    url(r'^canned-responses/$', CannedResponseViewSet.as_view(),
        name='reviewers-canned-response-list'),
]
