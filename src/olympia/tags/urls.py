from django.urls import re_path

from olympia.amo.views import frontend_view


urlpatterns = [
    re_path(r'^tag/(?P<tag_name>[^/]+)$', frontend_view, name='tags.detail'),
]
