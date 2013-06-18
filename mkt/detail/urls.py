from django.conf.urls import include, patterns, url
from django.http import HttpResponse

from mkt.purchase.urls import app_purchase_patterns
from mkt.ratings.urls import review_patterns
from mkt.receipts.urls import app_receipt_patterns
from mkt.stats.urls import app_stats_patterns
from . import views


urlpatterns = patterns('',
    url('^$', HttpResponse, name='detail'),
    url('^abuse$', HttpResponse, name='detail.abuse'),
    url('^privacy$', HttpResponse, name='detail.privacy'),

    # Merge app purchase / receipt patterns.
    ('^purchase/', include(app_purchase_patterns)),
    ('^purchase/', include(app_receipt_patterns)),

    # Statistics.
    ('^statistics/', include(app_stats_patterns)),

    # Ratings.
    ('^reviews/', include(review_patterns)),

    url('^activity/', views.app_activity, name='detail.app_activity'),
)
