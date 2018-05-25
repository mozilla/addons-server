from rest_framework.routers import SimpleRouter

from olympia.ratings.views import RatingViewSet


ratings_v3 = SimpleRouter()
ratings_v3.register(r'review', RatingViewSet, base_name='rating')

ratings_v4 = SimpleRouter()
ratings_v4.register(r'rating', RatingViewSet, base_name='rating')
