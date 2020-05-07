from django.conf.urls import url
from django.shortcuts import redirect

from olympia.addons.urls import ADDON_ID
from olympia.reviewers import views


# All URLs under /reviewers/
urlpatterns = (
    url(r'^$', views.dashboard, name='reviewers.dashboard'),
    url(r'^dashboard$',
        lambda request: redirect('reviewers.dashboard', permanent=True)),
    url(r'^queue/recommended$', views.queue_recommended,
        name='reviewers.queue_recommended'),
    url(r'^queue/extension$', views.queue_extension,
        name='reviewers.queue_extension'),
    url(r'^queue/theme_new$', views.queue_theme_nominated,
        name='reviewers.queue_theme_nominated'),
    url(r'^queue/theme_updates$', views.queue_theme_pending,
        name='reviewers.queue_theme_pending'),
    url(r'^queue/reviews$', views.queue_moderated,
        name='reviewers.queue_moderated'),
    url(r'^queue/application_versions\.json$', views.application_versions_json,
        name='reviewers.application_versions_json'),
    url(r'^queue/auto_approved', views.queue_auto_approved,
        name='reviewers.queue_auto_approved'),
    url(r'^queue/content_review', views.queue_content_review,
        name='reviewers.queue_content_review'),
    url(r'^queue/mad', views.queue_mad, name='reviewers.queue_mad'),
    url(r'^queue/needs_human_review', views.queue_needs_human_review,
        name='reviewers.queue_needs_human_review'),
    url(r'^queue/expired_info_requests', views.queue_expired_info_requests,
        name='reviewers.queue_expired_info_requests'),
    url(r'^unlisted_queue/all$', views.unlisted_list,
        name='reviewers.unlisted_queue_all'),
    url(r'^moderationlog$', views.ratings_moderation_log,
        name='reviewers.ratings_moderation_log'),
    url(r'^moderationlog/(\d+)$', views.ratings_moderation_log_detail,
        name='reviewers.ratings_moderation_log.detail'),
    url(r'^reviewlog$', views.reviewlog, name='reviewers.reviewlog'),
    url(r'^queue_version_notes/%s?$' % ADDON_ID, views.queue_version_notes,
        name='reviewers.queue_version_notes'),
    url(r'^queue_review_text/(\d+)?$', views.queue_review_text,
        name='reviewers.queue_review_text'),  # (?P<addon_id>[^/<>"']+)
    url(r'^queue_viewing$', views.queue_viewing,
        name='reviewers.queue_viewing'),
    url(r'^review_viewing$', views.review_viewing,
        name='reviewers.review_viewing'),
    # 'content' is not a channel, but is a special kind of review that we only
    # do for listed add-ons, so we abuse the channel parameter to handle that.
    url(r'^review(?:-(?P<channel>listed|unlisted|content))?/%s$' % ADDON_ID,
        views.review, name='reviewers.review'),
    url(r'^whiteboard/(?P<channel>listed|unlisted|content)/%s$' % ADDON_ID,
        views.whiteboard, name='reviewers.whiteboard'),
    url(r'^eula/%s$' % ADDON_ID, views.eula, name='reviewers.eula'),
    url(r'^privacy/%s$' % ADDON_ID, views.privacy, name='reviewers.privacy'),

    url(r'^performance/(?P<user_id>\d+)?$', views.performance,
        name='reviewers.performance'),
    url(r'^motd$', views.motd, name='reviewers.motd'),
    url(r'^motd/save$', views.save_motd, name='reviewers.save_motd'),
    url(r'^abuse-reports/%s$' % ADDON_ID, views.abuse_reports,
        name='reviewers.abuse_reports'),
    url(r'^leaderboard/$', views.leaderboard, name='reviewers.leaderboard'),
    url(r'^theme_background_images/(?P<version_id>[^ /]+)?$',
        views.theme_background_images,
        name='reviewers.theme_background_images'),
    url(r'^download-git-file/(?P<version_id>\d+)/(?P<filename>.*)/',
        views.download_git_stored_file,
        name='reviewers.download_git_file'),
)
