from django.shortcuts import redirect
from django.urls import include, re_path

from olympia.addons.urls import ADDON_ID
from olympia.reviewers import views
from olympia.users.urls import USER_ID


def queue_urls():
    return [
        re_path(
            views.reviewer_tables_registry[queue].url,
            getattr(views, views.reviewer_tables_registry[queue].view_name),
            kwargs={'tab': queue},
            name='reviewers.' + views.reviewer_tables_registry[queue].urlname,
        )
        for queue in views.reviewer_tables_registry
    ]


# All URLs under /reviewers/
urlpatterns = (
    re_path(r'^$', views.dashboard, name='reviewers.dashboard'),
    re_path(
        r'^dashboard$', lambda request: redirect('reviewers.dashboard', permanent=True)
    ),
    re_path(r'^queue/', include(queue_urls())),
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
        r'^review-version/%s/(?P<version>[^/<>]+)' % ADDON_ID,
        views.review_version_redirect,
        name='reviewers.review_version_redirect',
    ),
    re_path(
        r'^whiteboard/(?P<channel>listed|unlisted|content)/%s$' % ADDON_ID,
        views.whiteboard,
        name='reviewers.whiteboard',
    ),
    re_path(r'^eula/%s$' % ADDON_ID, views.eula, name='reviewers.eula'),
    re_path(r'^privacy/%s$' % ADDON_ID, views.privacy, name='reviewers.privacy'),
    re_path(r'^motd$', views.motd, name='reviewers.motd'),
    re_path(r'^motd/save$', views.save_motd, name='reviewers.save_motd'),
    re_path(
        r'^abuse-reports/%s$' % ADDON_ID,
        views.abuse_reports,
        name='reviewers.abuse_reports',
    ),
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
    re_path(
        r'^developer_profile/%s$' % USER_ID,
        views.developer_profile,
        name='reviewers.developer_profile',
    ),
    re_path(
        r'^usage_per_version/%s$' % ADDON_ID,
        views.usage_per_version,
        name='reviewers.usage_per_version',
    ),
)
