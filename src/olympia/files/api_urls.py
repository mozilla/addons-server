from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from .views import BrowseViewSet


browse = SimpleRouter()
browse.register(r'browse', BrowseViewSet, basename='browse')

urlpatterns = [
    url(r'', include(browse.urls)),
]
