from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from . import views

addons = SimpleRouter()
addons.register(r'addon', views.AddonViewSet)

# Router for children of /addons/addon/{addon_pk}/.
sub_addons = NestedSimpleRouter(addons, r'addon', lookup='addon')
sub_addons.register(r'versions', views.AddonVersionViewSet,
                    base_name='addon-version')

urlpatterns = patterns(
    '',

    url(r'', include(addons.urls)),
    url(r'', include(sub_addons.urls)),
    url(r'^search/$',
        views.AddonSearchView.as_view(),
        name='addon-search'),
)
