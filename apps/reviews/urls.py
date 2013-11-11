from django.conf.urls import include, patterns, url
from reviews.feeds import ReviewsRss
from . import views


def review_detail_patterns(prefix):
    # These all start with /addon/:id/reviews/:review_id/.
    return patterns('',
        url('^$', views.review_list, name='%s.reviews.detail' % prefix),
        url('^reply$', views.reply, name='%s.reviews.reply' % prefix),
        url('^flag$', views.flag, name='%s.reviews.flag' % prefix),
        url('^delete$', views.delete, name='%s.reviews.delete' % prefix),
        url('^edit$', views.edit, name='%s.reviews.edit' % prefix),
        url('^translate/(?P<language>[a-z]{2}(-[A-Z]{2})?)$', views.translate,
            name='%s.reviews.translate' % prefix),
    )


def review_patterns(prefix):
    return patterns('',
        url('^$', views.review_list, name='%s.reviews.list' % prefix),
        url('^add$', views.add, name='%s.reviews.add' % prefix),
        url('^(?P<review_id>\d+)/', include(review_detail_patterns(prefix))),
        url('^format:rss$', ReviewsRss(), name='%s.reviews.list.rss' % prefix),
        url('^user:(?P<user_id>\d+)$', views.review_list,
            name='%s.reviews.user' % prefix),
    )
