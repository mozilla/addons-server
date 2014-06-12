from django.conf.urls import include, patterns, url
from reviews.feeds import ReviewsRss
from . import views


# These all start with /addon/:id/reviews/:review_id/.
review_detail_patterns = patterns('',
    url('^$', views.review_list, name='addons.reviews.detail'),
    url('^reply$', views.reply, name='addons.reviews.reply'),
    url('^flag$', views.flag, name='addons.reviews.flag'),
    url('^delete$', views.delete, name='addons.reviews.delete'),
    url('^edit$', views.edit, name='addons.reviews.edit'),
    url('^translate/(?P<language>[a-z]{2}(-[A-Z]{2})?)$', views.translate,
        name='addons.reviews.translate'),
)


# These all start with /addon/:id/reviews/.
review_patterns = patterns('',
    url('^$', views.review_list, name='addons.reviews.list'),
    url('^add$', views.add, name='addons.reviews.add'),
    url('^(?P<review_id>\d+)/', include(review_detail_patterns)),
    url('^format:rss$', ReviewsRss(), name='addons.reviews.list.rss'),
    url('^user:(?P<user_id>\d+)$', views.review_list,
        name='addons.reviews.user'),
)
