from django.conf.urls import include, patterns, url
from django.http import HttpResponse

from mkt.ratings.feeds import RatingsRss
from reviews.views import delete as amo_delete, flag as amo_flag


DummyResponse = lambda *args, **kw: HttpResponse()


# These all start with /apps/<app_slug>/reviews/<review_id>/.
detail_patterns = patterns('',
    # Used by Fireplace.
    url('^$', DummyResponse, name='ratings.detail'),
    url('^edit$', DummyResponse, name='ratings.edit'),

    # Used by Reviewer Tools.
    url('^flag$', amo_flag, name='ratings.flag'),
    url('^delete$', amo_delete, name='ratings.delete'),
)


# These all start with /apps/<app_slug>/reviews/.
review_patterns = patterns('',
    # Used by Fireplace.
    url('^$', DummyResponse, name='ratings.list'),
    url('^add$', DummyResponse, name='ratings.add'),
    url('^(?P<review_id>\d+)/', include(detail_patterns)),
    url('^user:(?P<user_id>\d+)$', DummyResponse, name='ratings.user'),

    # TODO: The API should expose this.
    url('^format:rss$', RatingsRss(), name='ratings.list.rss'),
)
