from django.conf.urls import include, patterns, url

from tastypie.api import Api

import amo
from apps.editors.views import queue_viewing, review_viewing
from mkt.receipts.urls import receipt_patterns
from . import api, views, views_themes


reviewers_api = Api(api_name='reviewers')
reviewers_api.register(api.ReviewersSearchResource())

# All URLs under /reviewers/.
url_patterns = patterns('',
    url(r'^apps/$', views.home, name='reviewers.home'),
    url(r'^$', views.route_reviewer, name='reviewers'),
    url(r'^apps/queue/$', views.queue_apps,
        name='reviewers.apps.queue_pending'),
    url(r'^apps/queue/region/(?P<region>[^ /]+)?$', views.queue_region,
        name='reviewers.apps.queue_region'),
    url(r'^apps/queue/rereview/$', views.queue_rereview,
        name='reviewers.apps.queue_rereview'),
    url(r'^apps/queue/updates/$', views.queue_updates,
        name='reviewers.apps.queue_updates'),
    url(r'^apps/queue/escalated/$', views.queue_escalated,
        name='reviewers.apps.queue_escalated'),
    url(r'^apps/queue/moderated/$', views.queue_moderated,
        name='reviewers.apps.queue_moderated'),
    url(r'^apps/queue/device/$', views.queue_device,
        name='reviewers.apps.queue_device'),
    url(r'^apps/review/%s$' % amo.APP_SLUG, views.app_review,
        name='reviewers.apps.review'),
    url(r'^apps/review/%s/manifest$' % amo.APP_SLUG, views.app_view_manifest,
        name='reviewers.apps.review.manifest'),
    url(r'^apps/review/attachment/(\d+)$', views.attachment,
        name='reviewers.apps.review.attachment'),
    url(r'^apps/review/%s/abuse$' % amo.APP_SLUG, views.app_abuse,
        name='reviewers.apps.review.abuse'),
    url(r'^apps/logs$', views.logs, name='reviewers.apps.logs'),
    url(r'^apps/motd$', views.motd, name='reviewers.apps.motd'),
    url(r'^queue_viewing$', queue_viewing, name='editors.queue_viewing'),
    url(r'^review_viewing$', review_viewing, name='editors.review_viewing'),
    url(r'^apps/reviewing$', views.apps_reviewing,
        name='reviewers.apps.apps_reviewing'),

    url('^themes$', views_themes.home,
        name='reviewers.themes.home'),
    url('^themes/pending$', views_themes.themes_list,
        name='reviewers.themes.list'),
    url('^themes/flagged$', views_themes.themes_list,
        name='reviewers.themes.list_flagged',
        kwargs={'flagged': True}),
    url('^themes/updates$', views_themes.themes_list,
        name='reviewers.themes.list_rereview',
        kwargs={'rereview': True}),
    url('^themes/queue/$', views_themes.themes_queue,
        name='reviewers.themes.queue_themes'),
        url('^themes/queue/flagged$', views_themes.themes_queue_flagged,
        name='reviewers.themes.queue_flagged'),
    url('^themes/queue/updates$', views_themes.themes_queue_rereview,
        name='reviewers.themes.queue_rereview'),
    url('^themes/queue/commit$', views_themes.themes_commit,
        name='reviewers.themes.commit'),
    url('^themes/queue/single/(?P<slug>[^ /]+)$', views_themes.themes_single,
        name='reviewers.themes.single'),
    url('^themes/history/(?P<username>[^ /]+)?$',
        views_themes.themes_history, name='reviewers.themes.history'),
    url(r'^themes/logs$', views_themes.themes_logs,
        name='reviewers.themes.logs'),
    url('^themes/release$', views_themes.release_locks,
        name='reviewers.themes.release_locks'),
    url('^themes/logs/deleted/$', views_themes.deleted_themes,
        name='reviewers.themes.deleted'),
    url('^themes/search/$', views_themes.themes_search,
        name='reviewers.themes.search'),

    url(r'^receipt/', include(receipt_patterns)),
    url(r'^(?P<addon_id>\d+)/(?P<version_id>\d+)/mini-manifest$',
        views.mini_manifest, name='reviewers.mini_manifest'),
    url(r'^signed/%s/(?P<version_id>\d+)$' % amo.APP_SLUG,
        views.get_signed_packaged, name='reviewers.signed'),

    url(r'''^performance/(?P<username>[^/<>"']+)?$''', views.performance,
        name='reviewers.performance'),
    url(r'^leaderboard/$', views.leaderboard, name='reviewers.leaderboard'),
)

api_patterns = patterns('',
    url(r'^', include(reviewers_api.urls)),  # The API.
    url(r'^reviewers/app/(?P<pk>[^/<>"\']+)/approve/(?P<region>[^ /]+)?$',
        api.ApproveRegion.as_view(), name='approve-region'),
    url(r'^reviewers/reviewing', api.ReviewingView.as_view(),
        name='reviewing-list'),
)
