from django.conf.urls import patterns, url

from olympia.search.views import search


urlpatterns = patterns(
    '',
    url('^tag/(?P<tag_name>[^/]+)$', search, name='tags.detail'),
)
