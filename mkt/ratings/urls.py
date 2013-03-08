from django.conf.urls import include, patterns, url

from mkt.ratings.feeds import RatingsRss
from reviews.views import delete as amo_delete, flag as amo_flag

from . import views


# These all start with /apps/<app_slug>/reviews/<review_id>/.
detail_patterns = patterns('',
    url('^$', views.review_list, name='ratings.detail'),
    url('^flag$', amo_flag, name='ratings.flag'),
    url('^delete$', amo_delete, name='ratings.delete'),
    url('^edit$', views.edit, name='ratings.edit'),
)


# These all start with /apps/<app_slug>/reviews/.
review_patterns = patterns('',
    url('^$', views.review_list, name='ratings.list'),
    url('^add$', views.add, name='ratings.add'),
    url('^(?P<review_id>\d+)/', include(detail_patterns)),
    url('^format:rss$', RatingsRss(), name='ratings.list.rss'),
    url('^user:(?P<user_id>\d+)$', views.review_list, name='ratings.user'),
)


# These all start with /theme/<addon_id>/reviews/<review_id>/.
theme_detail_patterns = patterns('',
    url('^$', views.review_list, name='ratings.themes.detail'),
    url('^flag$', amo_flag, name='ratings.themes.flag'),
    url('^delete$', amo_delete, name='ratings.themes.delete'),
    url('^edit$', views.edit, name='ratings.themes.edit'),
)


# These all start with /theme/<addon_id>/reviews/.
theme_review_patterns = patterns('',
    url('^$', views.review_list, name='ratings.themes.list'),
    url('^add$', views.add, name='ratings.themes.add'),
    url('^(?P<review_id>\d+)/', include(theme_detail_patterns)),
    url('^format:rss$', RatingsRss(), name='ratings.themes.list.rss'),
    url('^user:(?P<user_id>\d+)$', views.review_list,
        name='ratings.themes.user'),
)
