from django.urls import include, re_path

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from olympia.bandwagon.views import CollectionAddonViewSet, CollectionViewSet

from . import views


accounts = SimpleRouter()
accounts.register(r'account', views.AccountViewSet, basename='account')

collections = NestedSimpleRouter(accounts, r'account', lookup='user')
collections.register(r'collections', CollectionViewSet, basename='collection')
sub_collections = NestedSimpleRouter(collections, r'collections', lookup='collection')
sub_collections.register('addons', CollectionAddonViewSet, basename='collection-addon')

notifications = NestedSimpleRouter(accounts, r'account', lookup='user')
notifications.register(
    r'notifications', views.AccountNotificationViewSet, basename='notification'
)

accounts_v4 = [
    re_path(
        r'^login/start/$', views.LoginStartView.as_view(), name='accounts.login_start'
    ),
    re_path(r'^session/$', views.SessionView.as_view(), name='accounts.session'),
    re_path(r'', include(accounts.urls)),
    re_path(r'^profile/$', views.ProfileView.as_view(), name='account-profile'),
    re_path(
        r'^super-create/$',
        views.AccountSuperCreate.as_view(),
        name='accounts.super-create',
    ),
    re_path(
        r'^unsubscribe/$',
        views.AccountNotificationUnsubscribeView.as_view(),
        name='account-unsubscribe',
    ),
    re_path(r'', include(collections.urls)),
    re_path(r'', include(sub_collections.urls)),
    re_path(r'', include(notifications.urls)),
]

accounts_v3 = accounts_v4 + [
    re_path(
        r'^authenticate/$',
        views.AuthenticateView.as_view(),
        name='accounts.authenticate',
    ),
]

auth_callback_patterns = [
    re_path(
        r'^authenticate-callback/$',
        views.AuthenticateView.as_view(),
        name='accounts.authenticate',
    ),
]
