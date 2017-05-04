from django.conf.urls import include, url
from django.views.generic.base import RedirectView

from rest_framework.routers import SimpleRouter

from . import views


accounts = SimpleRouter()
accounts.register(r'account', views.AccountViewSet, base_name='account')

urlpatterns = [
    url(r'^authenticate/$', views.AuthenticateView.as_view(),
        name='accounts.authenticate'),
    url(r'^login/$', views.LoginView.as_view(), name='accounts.login'),
    url(r'^login/start/$',
        views.LoginStartView.as_view(),
        name='accounts.login_start'),
    url(r'^session/$', views.SessionView.as_view(),
        name='accounts.session'),
    url(r'', include(accounts.urls)),
    url(r'account/$', views.AccountViewSet.as_view({'get': 'retrieve'}),
        name='account-self'),
    url(r'^profile/?$',
        RedirectView.as_view(pattern_name='account-self', permanent=True),
        name='accounts.profile'),
    url(r'^register/$', views.RegisterView.as_view(),
        name='accounts.register'),
    url(r'^super-create/$', views.AccountSuperCreate.as_view(),
        name='accounts.super-create'),
]
