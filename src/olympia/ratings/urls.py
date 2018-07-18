from django.conf.urls import include, url

from olympia.ratings.feeds import RatingsRss

from . import views


# These all start with /addon/:id/reviews/:review_id/.
rating_detail_patterns = [
    url('^$', views.review_list, name='addons.ratings.detail'),
    url('^reply$', views.reply, name='addons.ratings.reply'),
    url('^flag$', views.flag, name='addons.ratings.flag'),
    url('^delete$', views.delete, name='addons.ratings.delete'),
    url('^edit$', views.edit, name='addons.ratings.edit'),
]


urlpatterns = [
    url('^$', views.review_list, name='addons.ratings.list'),
    url('^add$', views.add, name='addons.ratings.add'),
    url('^(?P<review_id>\d+)/', include(rating_detail_patterns)),
    url('^format:rss$', RatingsRss(), name='addons.ratings.list.rss'),
    url(
        '^user:(?P<user_id>\d+)$',
        views.review_list,
        name='addons.ratings.user',
    ),
]
