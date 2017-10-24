from django.conf.urls import include, url

from rest_framework.routers import SimpleRouter

from olympia.ratings.views import ReviewViewSet


ratings = SimpleRouter()
ratings.register(r'review', ReviewViewSet, base_name='ratings')

urlpatterns = [
    url(r'', include(ratings.urls))
]
