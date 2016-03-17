from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter

from . import views

addons = SimpleRouter()
addons.register(r'addon', views.AddonViewSet)


urlpatterns = patterns(
    '',

    url(r'', include(addons.urls)),
    url(r'^search/$',
        views.AddonSearchView.as_view(),
        name='addon-search'),
)
