from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns(
    '',

    url(r'^addons/search/$',
        views.InternalAddonSearchView.as_view(),
        name='internal-addon-search'),
)
