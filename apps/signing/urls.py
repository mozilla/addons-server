from django.conf.urls import patterns, url

from amo.signing.views import AddonView

urlpatterns = patterns(
    '',
    url('addons/(?P<addon_name>[^/]+)/(?p<version>[^/]+)$',
        AddonView.as_view()),
)
