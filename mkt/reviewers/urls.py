from django.conf.urls import include, url

import amo
from apps.editors.views import queue_viewing, review_viewing
from mkt.receipts.urls import receipt_patterns
from . import views


# All URLs under /reviewers/.
urlpatterns = (
    url(r'^$', views.home, name='reviewers.home'),
    url(r'^apps/queue/$', views.queue_apps,
        name='reviewers.apps.queue_pending'),
    url(r'^apps/queue/rereview/$', views.queue_rereview,
        name='reviewers.apps.queue_rereview'),
    url(r'^apps/queue/updates/$', views.queue_updates,
        name='reviewers.apps.queue_updates'),
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
    url(r'^review_viewing$', review_viewing, name='editors.review_viewing'),
    url(r'^apps/reviewing$', views.apps_reviewing,
        name='reviewers.apps.apps_reviewing'),

    url('^themes/queue/$', views.themes_queue,
        name='reviewers.themes.queue_themes'),
    url('^themes/queue/commit$', views.themes_commit,
        name='reviewers.themes.commit'),
    url('^themes/queue/more$', views.themes_more,
        name='reviewers.themes.more'),
    url('^themes/queue/single/(?P<slug>[^ /]+)$', views.themes_single,
        name='reviewers.themes.single'),
    url('^themes/history/(?P<username>[^ /]+)?$',
        views.themes_history, name='reviewers.themes.history'),
    url(r'^themes/logs$', views.themes_logs, name='reviewers.themes.logs'),

    url(r'^receipt/', include(receipt_patterns)),
    url(r'^(?P<addon_id>\d+)/(?P<version_id>\d+)/mini-manifest$',
        views.mini_manifest, name='reviewers.mini_manifest'),
    url(r'^signed/%s/(?P<version_id>\d+)$' % amo.APP_SLUG,
        views.get_signed_packaged, name='reviewers.signed'),

    url(r'''^performance/(?P<username>[^/<>"']+)?$''', views.performance,
        name='reviewers.performance'),
    url(r'^leaderboard/$', views.leaderboard, name='reviewers.leaderboard'),
)
