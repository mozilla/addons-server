from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from . import views


collections = SimpleRouter()
collections.register(r'collection', views.CollectionViewSet,
                     base_name='collection')
sub_collections = NestedSimpleRouter(collections, r'collection',
                                     lookup='collection')
sub_collections.register('addons', views.CollectionAddonViewSet,
                         base_name='collection-addon')

urlpatterns = [
    url(r'', include(collections.urls)),
    url(r'', include(sub_collections.urls)),
]
