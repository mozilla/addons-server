from django.urls import include, re_path

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from olympia.activity.views import VersionReviewNotesViewSet
from olympia.files.views import FileUploadViewSet
from olympia.tags.views import TagListView

from .views import (
    AddonAuthorViewSet,
    AddonAutoCompleteSearchView,
    AddonBrowserMappingView,
    AddonFeaturedView,
    AddonPendingAuthorViewSet,
    AddonPreviewViewSet,
    AddonRecommendationView,
    AddonSearchView,
    AddonVersionViewSet,
    AddonViewSet,
    CompatOverrideView,
    LanguageToolsView,
    ReplacementAddonView,
    StaticCategoryView,
)


addons = SimpleRouter()
addons.register(r'addon', AddonViewSet, basename='addon')

# Router for children of /addons/addon/{addon_pk}/.
sub_addons = NestedSimpleRouter(addons, r'addon', lookup='addon')
sub_addons.register('versions', AddonVersionViewSet, basename='addon-version')
sub_addons.register('previews', AddonPreviewViewSet, basename='addon-preview')
sub_addons.register('authors', AddonAuthorViewSet, basename='addon-author')
sub_addons.register(
    'pending-authors', AddonPendingAuthorViewSet, basename='addon-pending-author'
)
sub_versions = NestedSimpleRouter(sub_addons, r'versions', lookup='version')
sub_versions.register(
    r'reviewnotes', VersionReviewNotesViewSet, basename='version-reviewnotes'
)

uploads = SimpleRouter()
uploads.register(r'upload', FileUploadViewSet, basename='addon-upload')

urls = [
    re_path(r'', include(addons.urls)),
    re_path(r'', include(sub_addons.urls)),
    re_path(r'', include(sub_versions.urls)),
    re_path(
        r'^autocomplete/$',
        AddonAutoCompleteSearchView.as_view(),
        name='addon-autocomplete',
    ),
    re_path(r'^search/$', AddonSearchView.as_view(), name='addon-search'),
    re_path(r'^categories/$', StaticCategoryView.as_view(), name='category-list'),
    re_path(
        r'^language-tools/$', LanguageToolsView.as_view(), name='addon-language-tools'
    ),
    re_path(
        r'^replacement-addon/$',
        ReplacementAddonView.as_view(),
        name='addon-replacement-addon',
    ),
    re_path(
        r'^recommendations/$',
        AddonRecommendationView.as_view(),
        name='addon-recommendations',
    ),
    re_path(
        r'^browser-mappings/$',
        AddonBrowserMappingView.as_view(),
        name='addon-browser-mappings',
    ),
]

addons_v3 = urls + [
    re_path(
        r'^compat-override/$',
        CompatOverrideView.as_view(),
        name='addon-compat-override',
    ),
    re_path(r'^featured/$', AddonFeaturedView.as_view(), name='addon-featured'),
]

addons_v4 = urls

addons_v5 = addons_v4 + [
    re_path(r'', include(uploads.urls)),
    re_path(r'^tags/$', TagListView.as_view(), name='tag-list'),
]
