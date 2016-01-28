from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^authenticate/$', views.AuthenticateView.as_view(),
        name='accounts.authenticate'),
    # TODO: Remove the authorize URL once the FxA callback has been set to
    # authenticate for a while.
    url(r'^authorize/$', views.AuthenticateView.as_view()),
    url(r'^login/$', views.LoginView.as_view(), name='accounts.login'),
    url(r'^profile/$', views.ProfileView.as_view(), name='accounts.profile'),
    url(r'^register/$', views.RegisterView.as_view(),
        name='accounts.register'),
    url(r'^source/$', views.AccountSourceView.as_view(),
        name='accounts.source'),
]
