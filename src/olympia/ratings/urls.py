from django.conf.urls import include, url

from olympia.ratings.feeds import RatingsRss

from . import views


# These all start with /addon/:id/reviews/:review_id/.
rating_detail_patterns = [
    url(r'^$', views.review_list, name='addons.ratings.detail'),
    url(r'^reply$', views.reply, name='addons.ratings.reply'),
    url(r'^flag$', views.flag, name='addons.ratings.flag'),
    url(r'^delete$', views.delete, name='addons.ratings.delete'),
    url(r'^edit$', views.edit, name='addons.ratings.edit'),
]


urlpatterns = [
    url(r'^$', views.review_list, name='addons.ratings.list'),
    url(r'^add$', views.add, name='addons.ratings.add'),
    url(r'^(?P<review_id>\d+)/', include(rating_detail_patterns)),
    url(r'^format:rss$', RatingsRss(), name='addons.ratings.list.rss'),
    url(r'^user:(?P<user_id>\d+)$', views.review_list,
        name='addons.ratings.user'),
]
