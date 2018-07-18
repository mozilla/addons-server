from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from olympia.bandwagon.views import CollectionAddonViewSet, CollectionViewSet

from . import views


accounts = SimpleRouter()
accounts.register(r'account', views.AccountViewSet, base_name='account')

collections = NestedSimpleRouter(accounts, r'account', lookup='user')
collections.register(r'collections', CollectionViewSet, base_name='collection')
sub_collections = NestedSimpleRouter(
    collections, r'collections', lookup='collection'
)
sub_collections.register(
    'addons', CollectionAddonViewSet, base_name='collection-addon'
)

notifications = NestedSimpleRouter(accounts, r'account', lookup='user')
notifications.register(
    r'notifications',
    views.AccountNotificationViewSet,
    base_name='notification',
)

urlpatterns = [
    url(
        r'^authenticate/$',
        views.AuthenticateView.as_view(),
        name='accounts.authenticate',
    ),
    url(
        r'^login/start/$',
        views.LoginStartView.as_view(),
        name='accounts.login_start',
    ),
    url(r'^session/$', views.SessionView.as_view(), name='accounts.session'),
    url(r'', include(accounts.urls)),
    url(r'^profile/$', views.ProfileView.as_view(), name='account-profile'),
    url(
        r'^super-create/$',
        views.AccountSuperCreate.as_view(),
        name='accounts.super-create',
    ),
    url(r'', include(collections.urls)),
    url(r'', include(sub_collections.urls)),
    url(r'', include(notifications.urls)),
]
