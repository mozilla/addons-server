from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter
from rest_framework_nested.routers import NestedSimpleRouter

from olympia.reviews.views import ReviewViewSet
from . import views


accounts = SimpleRouter()
accounts.register(r'account', views.AccountViewSet, base_name='account')

# Router for children of /accounts/account/{account_pk}/.
sub_accounts = NestedSimpleRouter(accounts, r'account', lookup='account')
sub_accounts.register('reviews', ReviewViewSet, base_name='account-review')


urlpatterns = [
    url(r'', include(accounts.urls)),
    url(r'', include(sub_accounts.urls)),
    url(r'^authenticate/$', views.AuthenticateView.as_view(),
        name='accounts.authenticate'),
    url(r'^login/$', views.LoginView.as_view(), name='accounts.login'),
    url(r'^login/start/$',
        views.LoginStartView.as_view(),
        name='accounts.login_start'),
    url(r'^profile/$', views.ProfileView.as_view(), name='accounts.profile'),
    url(r'^register/$', views.RegisterView.as_view(),
        name='accounts.register'),
    url(r'^super-create/$', views.AccountSuperCreate.as_view(),
        name='accounts.super-create'),
]
