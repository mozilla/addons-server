from django.urls import include, re_path

from rest_framework.routers import SimpleRouter

from .views import (
    AddonReviewerViewSet,
)


addons = SimpleRouter()
addons.register(r'addon', AddonReviewerViewSet, basename='reviewers-addon')

urlpatterns = [
    re_path(r'', include(addons.urls)),
]
