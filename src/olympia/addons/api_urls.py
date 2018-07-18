from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from olympia.activity.views import VersionReviewNotesViewSet

from .views import (
    AddonAutoCompleteSearchView,
    AddonFeaturedView,
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
addons.register(r'addon', AddonViewSet, base_name='addon')

# Router for children of /addons/addon/{addon_pk}/.
sub_addons = NestedSimpleRouter(addons, r'addon', lookup='addon')
sub_addons.register('versions', AddonVersionViewSet, base_name='addon-version')
sub_versions = NestedSimpleRouter(sub_addons, r'versions', lookup='version')
sub_versions.register(
    r'reviewnotes', VersionReviewNotesViewSet, base_name='version-reviewnotes'
)

urlpatterns = [
    url(r'', include(addons.urls)),
    url(r'', include(sub_addons.urls)),
    url(r'', include(sub_versions.urls)),
    url(
        r'^autocomplete/$',
        AddonAutoCompleteSearchView.as_view(),
        name='addon-autocomplete',
    ),
    url(r'^search/$', AddonSearchView.as_view(), name='addon-search'),
    url(r'^featured/$', AddonFeaturedView.as_view(), name='addon-featured'),
    url(r'^categories/$', StaticCategoryView.as_view(), name='category-list'),
    url(
        r'^language-tools/$',
        LanguageToolsView.as_view(),
        name='addon-language-tools',
    ),
    url(
        r'^replacement-addon/$',
        ReplacementAddonView.as_view(),
        name='addon-replacement-addon',
    ),
    url(
        r'^compat-override/$',
        CompatOverrideView.as_view(),
        name='addon-compat-override',
    ),
    url(
        r'^recommendations/$',
        AddonRecommendationView.as_view(),
        name='addon-recommendations',
    ),
]
