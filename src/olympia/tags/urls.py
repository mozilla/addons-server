from django.conf.urls import url

from olympia.search.views import search


urlpatterns = [url('^tag/(?P<tag_name>[^/]+)$', search, name='tags.detail')]
