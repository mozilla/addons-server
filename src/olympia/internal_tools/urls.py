from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns(
    '',

    url(r'^addons/search/$',
        views.InternalAddonSearchView.as_view(),
        name='internal-addon-search'),
    url(r'^accounts/login/start/$',
        views.LoginStartView.as_view(),
        name='internal-login-start'),
    url(r'^accounts/login/$',
        views.LoginView.as_view(),
        name='internal-login'),
)
