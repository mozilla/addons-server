from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from olympia.reviewers.views import AddonReviewerViewSet


addons = SimpleRouter()
addons.register(r'addon', AddonReviewerViewSet, base_name='reviewers-addon')

urlpatterns = [url(r'', include(addons.urls))]
