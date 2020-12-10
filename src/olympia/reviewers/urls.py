from django.urls import re_path
from django.shortcuts import redirect

from olympia.addons.urls import ADDON_ID
from olympia.reviewers import views


# All URLs under /reviewers/
urlpatterns = (
    re_path(r'^$', views.dashboard, name='reviewers.dashboard'),
    re_path(
        r'^dashboard$', lambda request: redirect('reviewers.dashboard', permanent=True)
    ),
    re_path(
        r'^queue/recommended$',
        views.queue_recommended,
        name='reviewers.queue_recommended',
    ),
    re_path(
        r'^queue/extension$', views.queue_extension, name='reviewers.queue_extension'
    ),
    re_path(
        r'^queue/theme_new$',
        views.queue_theme_nominated,
        name='reviewers.queue_theme_nominated',
    ),
    re_path(
        r'^queue/theme_updates$',
        views.queue_theme_pending,
        name='reviewers.queue_theme_pending',
    ),
    re_path(
        r'^queue/reviews$', views.queue_moderated, name='reviewers.queue_moderated'
    ),
    re_path(
        r'^queue/application_versions\.json$',
        views.application_versions_json,
        name='reviewers.application_versions_json',
    ),
    re_path(
        r'^queue/auto_approved',
        views.queue_auto_approved,
        name='reviewers.queue_auto_approved',
    ),
    re_path(
        r'^queue/content_review',
        views.queue_content_review,
        name='reviewers.queue_content_review',
    ),
    re_path(r'^queue/mad', views.queue_mad, name='reviewers.queue_mad'),
    re_path(r'^queue/scanners', views.queue_scanners, name='reviewers.queue_scanners'),
    re_path(
        r'queue/pending_rejection',
        views.queue_pending_rejection,
        name='reviewers.queue_pending_rejection',
    ),
    re_path(
        r'^unlisted_queue/all$',
        views.unlisted_list,
        name='reviewers.unlisted_queue_all',
    ),
    re_path(
        r'^moderationlog$',
        views.ratings_moderation_log,
        name='reviewers.ratings_moderation_log',
    ),
    re_path(
        r'^moderationlog/(\d+)$',
        views.ratings_moderation_log_detail,
        name='reviewers.ratings_moderation_log.detail',
    ),
    re_path(r'^reviewlog$', views.reviewlog, name='reviewers.reviewlog'),
    re_path(
        r'^queue_version_notes/%s?$' % ADDON_ID,
        views.queue_version_notes,
        name='reviewers.queue_version_notes',
    ),
    re_path(
        r'^queue_review_text/(\d+)?$',
        views.queue_review_text,
        name='reviewers.queue_review_text',
    ),  # (?P<addon_id>[^/<>"']+)
    re_path(r'^queue_viewing$', views.queue_viewing, name='reviewers.queue_viewing'),
    re_path(r'^review_viewing$', views.review_viewing, name='reviewers.review_viewing'),
    # 'content' is not a channel, but is a special kind of review that we only
    # do for listed add-ons, so we abuse the channel parameter to handle that.
    re_path(
        r'^review(?:-(?P<channel>listed|unlisted|content))?/%s$' % ADDON_ID,
        views.review,
        name='reviewers.review',
    ),
    re_path(
        r'^whiteboard/(?P<channel>listed|unlisted|content)/%s$' % ADDON_ID,
        views.whiteboard,
        name='reviewers.whiteboard',
    ),
    re_path(r'^eula/%s$' % ADDON_ID, views.eula, name='reviewers.eula'),
    re_path(r'^privacy/%s$' % ADDON_ID, views.privacy, name='reviewers.privacy'),
    re_path(
        r'^performance/(?P<user_id>\d+)?$',
        views.performance,
        name='reviewers.performance',
    ),
    re_path(r'^motd$', views.motd, name='reviewers.motd'),
    re_path(r'^motd/save$', views.save_motd, name='reviewers.save_motd'),
    re_path(
        r'^abuse-reports/%s$' % ADDON_ID,
        views.abuse_reports,
        name='reviewers.abuse_reports',
    ),
    re_path(r'^leaderboard/$', views.leaderboard, name='reviewers.leaderboard'),
    re_path(
        r'^theme_background_images/(?P<version_id>[^ /]+)?$',
        views.theme_background_images,
        name='reviewers.theme_background_images',
    ),
    re_path(
        r'^download-git-file/(?P<version_id>\d+)/(?P<filename>.*)/',
        views.download_git_stored_file,
        name='reviewers.download_git_file',
    ),
)
