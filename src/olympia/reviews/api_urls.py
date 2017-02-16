from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from olympia.reviews.views import ReviewViewSet


reviews = SimpleRouter()
reviews.register(r'review', ReviewViewSet)

urlpatterns = [
    url(r'', include(reviews.urls))
]
