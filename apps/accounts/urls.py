from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^authorize/$', views.AuthorizeView.as_view(),
        name='accounts.authorize'),
    url(r'^login/$', views.LoginView.as_view(), name='accounts.login'),
    url(r'^profile/$', views.ProfileView.as_view(), name='accounts.profile'),
    url(r'^register/$', views.RegisterView.as_view(),
        name='accounts.register'),
]
