from django.conf.urls.defaults import url

import amo
from . import views


# All URLs under /reviewers/.
urlpatterns = (
    url(r'^$', views.home, name='reviewers.home'),
    url(r'^apps/queue/$', views.queue_apps,
        name='reviewers.apps.queue_pending'),
    url(r'^apps/review/%s$' % amo.APP_SLUG, views.app_review,
        name='reviewers.apps.review'),
    url(r'^apps/logs$', views.logs, name='reviewers.apps.logs'),
    url(r'^apps/motd$', views.motd, name='reviewers.apps.motd'),
    url(r'^receipt/verify/%s$' % amo.APP_SLUG, views.verify,
        name='reviewers.receipt.verify'),
    url(r'^receipt/issue/%s$' % amo.APP_SLUG, views.issue,
        name='reviewers.receipt.issue'),
    url(r'^receipt/check/%s$' % amo.APP_SLUG, views.check,
        name='reviewers.receipt.check'),
)
