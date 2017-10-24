from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from olympia.ratings.views import ReviewViewSet


reviews = SimpleRouter()
reviews.register(r'review', ReviewViewSet, base_name='review')

urlpatterns = [
    url(r'', include(reviews.urls))
]
