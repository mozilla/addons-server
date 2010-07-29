from django.conf.urls.defaults import patterns, url, include
from reviews.feeds import ReviewsRss
from . import views


# These all start with /addon/:id/reviews/:review_id/.
detail_patterns = patterns('',
    url('^$', views.review_list, name='reviews.detail'),
    url('^reply$', views.reply, name='reviews.reply'),
    url('^flag$', views.flag, name='reviews.flag'),
    url('^delete$', views.delete, name='reviews.delete'),
    url('^edit$', views.edit, name='reviews.edit'),
)

urlpatterns = patterns('',
    url('^$', views.review_list, name='reviews.list'),
    url('^add$', views.add, name='reviews.add'),
    url('^(?P<review_id>\d+)/', include(detail_patterns)),
    url('^format:rss$', ReviewsRss(), name='reviews.list.rss'),
    url('^user:(?P<user_id>\d+)$', views.review_list, name='reviews.user'),
)
