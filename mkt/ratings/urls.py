from django.conf.urls import include, patterns, url
from django.http import HttpResponse

from mkt.ratings.feeds import RatingsRss
from reviews.views import delete as amo_delete, flag as amo_flag


# These all start with /apps/<app_slug>/reviews/<review_id>/.
detail_patterns = patterns('',
    # Used by Fireplace.
    url('^$', HttpResponse, name='ratings.detail'),
    url('^edit$', HttpResponse, name='ratings.edit'),

    # Used by Reviewer Tools.
    url('^flag$', amo_flag, name='ratings.flag'),
    url('^delete$', amo_delete, name='ratings.delete'),
)


# These all start with /apps/<app_slug>/reviews/.
review_patterns = patterns('',
    # Used by Fireplace.
    url('^$', HttpResponse, name='ratings.list'),
    url('^add$', HttpResponse, name='ratings.add'),
    url('^(?P<review_id>\d+)/', include(detail_patterns)),
    url('^user:(?P<user_id>\d+)$', HttpResponse, name='ratings.user'),

    # TODO: The API should expose this.
    url('^format:rss$', RatingsRss(), name='ratings.list.rss'),
)
