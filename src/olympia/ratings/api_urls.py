from django.conf.urls import include, url
from rest_framework.routers import SimpleRouter

from olympia.ratings.views import RatingViewSet


ratings = SimpleRouter()
ratings.register(r'review', RatingViewSet, base_name='rating')

urlpatterns = [
    url(r'', include(ratings.urls))
]
