from django.conf.urls.defaults import patterns, url, include

from . import views


# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
    url('^$', views.addon_detail, name='addons.detail'),

    ('^reviews/', include('reviews.urls')),
    ('^statistics/', include('stats.urls')),
)


urlpatterns = patterns('',
    # URLs for a single add-on.
    ('^addon/(?P<addon_id>\d+)/', include(detail_patterns)),
)
