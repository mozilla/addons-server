from django.conf.urls import url

from olympia.amo.views import frontend_view


urlpatterns = [
    url(r'^tag/(?P<tag_name>[^/]+)$', frontend_view, name='tags.detail'),
]
