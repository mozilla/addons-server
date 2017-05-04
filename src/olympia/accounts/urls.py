from django.conf.urls import url
from django.views.generic.base import RedirectView

from . import views


urlpatterns = [
    url(r'^authenticate/$', views.AuthenticateView.as_view(),
        name='accounts.authenticate'),
    url(r'^login/$', views.LoginView.as_view(), name='accounts.login'),
    url(r'^login/start/$',
        views.LoginStartView.as_view(),
        name='accounts.login_start'),
    url(r'^session/$', views.SessionView.as_view(),
        name='accounts.session'),
    url(r'^account/(?:(?P<user_id>\d+)/)?$', views.ProfileView.as_view(),
        name='accounts.account'),
    url(r'^profile/?$',
        RedirectView.as_view(pattern_name='accounts.account', permanent=True),
        name='accounts.profile'),
    url(r'^register/$', views.RegisterView.as_view(),
        name='accounts.register'),
    url(r'^super-create/$', views.AccountSuperCreate.as_view(),
        name='accounts.super-create'),
]
