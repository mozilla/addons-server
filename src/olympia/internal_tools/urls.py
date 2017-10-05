from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from . import views

addons = SimpleRouter()
addons.register(r'addon', views.InternalAddonViewSet,
                base_name='internal-addon')


urlpatterns = [
    url(r'^addons/search/$',
        views.InternalAddonSearchView.as_view(),
        name='internal-addon-search'),
    url(r'^addons/', include(addons.urls)),
    url(r'^accounts/login/start/$',
        views.LoginStartView.as_view(),
        name='internal-login-start'),
]
