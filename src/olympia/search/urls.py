from django.conf.urls import url

from olympia.amo.views import frontend_view


urlpatterns = [
    url(r'^(?:es)?$', frontend_view, name='search.search'),
]
