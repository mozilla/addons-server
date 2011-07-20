from django.conf.urls.defaults import patterns, url, include
from reviews.feeds import ReviewsRss
from . import views


# These all start with /addon/:id/reviews/:review_id/.
detail_patterns = patterns('',
    url('^$', views.impala_review_list, name='i_reviews.detail'),
    url('^reply$', views.impala_reply, name='i_reviews.reply'),
    url('^edit$', views.edit, name='i_reviews.edit'),
)

urlpatterns = patterns('',
    url('^$', views.impala_review_list, name='i_reviews.list'),
    url('^add$', views.impala_add, name='i_reviews.add'),
    url('^(?P<review_id>\d+)/', include(detail_patterns)),
    url('^format:rss$', ReviewsRss(), name='reviews.list.rss'),
    url('^user:(?P<user_id>\d+)$', views.impala_review_list, name='i_reviews.user'),
)
