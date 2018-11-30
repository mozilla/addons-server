from rest_framework.routers import SimpleRouter

from olympia.ratings.views import RatingViewSet


ratings_v3 = SimpleRouter()
ratings_v3.register(r'review', RatingViewSet, basename='rating')

ratings_v4 = SimpleRouter()
ratings_v4.register(r'rating', RatingViewSet, basename='rating')
