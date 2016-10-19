from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter

from olympia.addons.views import AddonViewSet

from . import views

addons = SimpleRouter()
addons.register(r'addon', AddonViewSet, base_name='internal-addon')


urlpatterns = patterns(
    '',

    url(r'^addons/search/$',
        views.InternalAddonSearchView.as_view(),
        name='internal-addon-search'),
    url(r'^addons/', include(addons.urls)),
    url(r'^accounts/login/start/$',
        views.LoginStartView.as_view(),
        name='internal-login-start'),
    url(r'^accounts/login/$',
        views.LoginView.as_view(),
        name='internal-login'),
)
