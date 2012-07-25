from django.conf.urls.defaults import include, url

import amo
from apps.editors.views import queue_viewing
from mkt.receipts.urls import receipt_patterns
from . import views


# All URLs under /reviewers/.
urlpatterns = (
    url(r'^$', views.home, name='reviewers.home'),
    url(r'^apps/queue/$', views.queue_apps,
        name='reviewers.apps.queue_pending'),
    url(r'^apps/queue/rereview/$', views.queue_rereview,
        name='reviewers.apps.queue_rereview'),
    url(r'^apps/queue/escalated/$', views.queue_escalated,
        name='reviewers.apps.queue_escalated'),
    url(r'^apps/queue/moderated$', views.queue_moderated,
        name='reviewers.apps.queue_moderated'),
    url(r'^apps/review/%s$' % amo.APP_SLUG, views.app_review,
        name='reviewers.apps.review'),
    url(r'^apps/review/%s/manifest$' % amo.APP_SLUG, views.app_view_manifest,
        name='reviewers.apps.review.manifest'),
    url(r'^apps/review/%s/abuse$' % amo.APP_SLUG, views.app_abuse,
        name='reviewers.apps.review.abuse'),
    url(r'^apps/logs$', views.logs, name='reviewers.apps.logs'),
    url(r'^apps/motd$', views.motd, name='reviewers.apps.motd'),
    url(r'^queue_viewing$', queue_viewing, name='editors.queue_viewing'),

    url(r'^receipt/', include(receipt_patterns))
)
