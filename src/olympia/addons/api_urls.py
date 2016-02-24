from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns(
    '',

    url('^search/$',
        views.AddonSearchView.as_view(),
        name='addon-search'),
)
