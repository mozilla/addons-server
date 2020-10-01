from django.urls import re_path

from olympia.amo.views import frontend_view


urlpatterns = [
    re_path(r'^(?:es)?$', frontend_view, name='search.search'),
]
