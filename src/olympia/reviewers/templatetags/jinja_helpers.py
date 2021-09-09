import datetime

from django.conf import settings
from django.utils.translation import gettext

import jinja2

from django_jinja import library

from olympia import amo
from olympia.access import acl
from olympia.addons.templatetags.jinja_helpers import new_context
from olympia.ratings.permissions import user_can_delete_rating
from olympia.reviewers.models import ReviewerScore
from olympia.reviewers.templatetags import code_manager


@library.global_function
def file_review_status(addon, file):
    if file.status == amo.STATUS_DISABLED:
        if file.reviewed is not None:
            return gettext('Rejected')
        # Can't assume that if the reviewed date is missing its
        # unreviewed.  Especially for versions.
        else:
            return gettext('Rejected or Unreviewed')
    return file.STATUS_CHOICES.get(file.status, gettext('[status:%s]') % file.status)


@library.global_function
def version_status(addon, version):
    if version.deleted:
        return gettext('Deleted')
    return version.file.STATUS_CHOICES.get(
        version.file.status, gettext('[status:%s]') % version.file.status
    )


@library.global_function
@jinja2.pass_context
def queue_tabnav(context):
    """Returns tuple of tab navigation for the queue pages.

    Each tuple contains three elements: (tab_code, page_url, tab_text)
    """
    request = context['request']
    listed = not context.get('unlisted')

    if listed:
        tabnav = []
        if acl.action_allowed(request, amo.permissions.ADDONS_RECOMMENDED_REVIEW):
            tabnav.append(('recommended', 'queue_recommended', gettext('Recommended')))
        if acl.action_allowed(request, amo.permissions.ADDONS_REVIEW):
            tabnav.append(
                (
                    'extension',
                    'queue_extension',
                    '🛠️ ' + gettext('Other Pending Review'),
                )
            )
            tabnav.append(
                ('scanners', 'queue_scanners', gettext('Flagged By Scanners'))
            )
            tabnav.append(('mad', 'queue_mad', gettext('Flagged for Human Review')))
        if acl.action_allowed(request, amo.permissions.STATIC_THEMES_REVIEW):
            tabnav.extend(
                (
                    (
                        'theme_nominated',
                        'queue_theme_nominated',
                        '🎨 ' + gettext('New'),
                    ),
                    (
                        'theme_pending',
                        'queue_theme_pending',
                        '🎨 ' + gettext('Updates'),
                    ),
                )
            )
        if acl.action_allowed(request, amo.permissions.RATINGS_MODERATE):
            tabnav.append(('moderated', 'queue_moderated', gettext('Rating Reviews')))

        if acl.action_allowed(request, amo.permissions.ADDONS_REVIEW):
            tabnav.append(
                ('auto_approved', 'queue_auto_approved', gettext('Auto Approved'))
            )

        if acl.action_allowed(request, amo.permissions.ADDONS_CONTENT_REVIEW):
            tabnav.append(
                ('content_review', 'queue_content_review', gettext('Content Review'))
            )

        if acl.action_allowed(request, amo.permissions.REVIEWS_ADMIN):
            tabnav.append(
                (
                    'pending_rejection',
                    'queue_pending_rejection',
                    gettext('Pending Rejection'),
                )
            )
    else:
        tabnav = [
            ('all', 'unlisted_queue_all', gettext('All Unlisted Add-ons')),
            (
                'pending_manual_approval',
                'unlisted_queue_pending_manual_approval',
                gettext('Unlisted Add-ons Pending Manual Approval'),
            ),
        ]

    return tabnav


@library.global_function
@library.render_with('reviewers/includes/reviewers_score_bar.html')
@jinja2.pass_context
def reviewers_score_bar(context, types=None, addon_type=None):
    user = context.get('user')

    return new_context(
        dict(
            request=context.get('request'),
            amo=amo,
            settings=settings,
            points=ReviewerScore.get_recent(user, addon_type=addon_type),
            total=ReviewerScore.get_total(user),
            **ReviewerScore.get_leaderboards(user, types=types, addon_type=addon_type),
        )
    )


@library.global_function
@library.render_with('reviewers/includes/files_view.html')
@jinja2.pass_context
def file_view(context, version):
    return new_context(
        dict(
            # We don't need the hashes in the template.
            file=version.file,
            amo=context.get('amo'),
            addon=context.get('addon'),
            latest_not_disabled_version=context.get('latest_not_disabled_version'),
            # This allows the template to call waffle.flag().
            request=context.get('request'),
            base_version=context.get('base_version'),
            version=version,
        )
    )


@library.global_function
@jinja2.pass_context
def is_expired_lock(context, lock):
    return lock.expiry < datetime.datetime.now()


@library.global_function
def code_manager_url(page, addon_id, version_id, base_version_id=None):
    return code_manager.code_manager_url(page, addon_id, version_id, base_version_id)


@library.global_function
@jinja2.pass_context
def check_review_delete(context, rating):
    return user_can_delete_rating(context['request'], rating)


@library.filter
def format_score(value):
    return f'{value:0.0f}%' if value and value >= 0 else 'n/a'
