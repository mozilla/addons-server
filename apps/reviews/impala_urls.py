from django.conf.urls.defaults import patterns, url, include
from reviews.feeds import ReviewsRss
from . import views


# These all start with /addon/:id/reviews/:review_id/.

urlpatterns = patterns('',
    url('^$', views.impala_review_list, name='i_reviews.list'),
)
