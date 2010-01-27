from django.conf.urls.defaults import patterns, url, include
from django.shortcuts import redirect


# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
    # ('^$', views.addon_detail, name='addons.detail'),

    ('^reviews/', include('reviews.urls')),
)


urlpatterns = patterns('',
    # URLs for a single add-on.
    ('^addon/(?P<addon_id>\d+)/', include(detail_patterns)),
)
