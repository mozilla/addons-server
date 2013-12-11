from django.conf.urls import patterns, url

from rest_framework import routers

from mkt.ratings.feeds import RatingsRss
from mkt.ratings.views import RatingViewSet

from reviews.views import delete as amo_delete, flag as amo_flag


router = routers.DefaultRouter()
router.register(r'rating', RatingViewSet, base_name='ratings')
urlpatterns = router.urls


# These all start with /apps/<app_slug>/reviews/<review_id>/.
detail_patterns = patterns('',
    # Used by Reviewer Tools.
    url('^flag$', amo_flag, name='ratings.flag'),
    url('^delete$', amo_delete, name='ratings.delete'),
)


# These all start with /apps/<app_slug>/reviews/.
review_patterns = patterns('',
    # TODO: The API should expose this.
    url('^format:rss$', RatingsRss(), name='ratings.list.rss'),
)
