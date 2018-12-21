from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from .views import AddonReviewerViewSet, BrowseViewSet


addons = SimpleRouter()
addons.register(r'addon', AddonReviewerViewSet, basename='reviewers-addon')
addons.register(r'browse', BrowseViewSet, basename='reviewers-browse')

urlpatterns = [
    url(r'', include(addons.urls)),
]
