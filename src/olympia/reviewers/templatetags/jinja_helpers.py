import datetime

import jinja2

from django_jinja import library

from olympia import amo
from olympia.access import acl
from olympia.amo.templatetags.jinja_helpers import new_context
from olympia.ratings.permissions import user_can_delete_rating
from olympia.reviewers.templatetags import code_manager


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
        if acl.action_allowed_for(request.user, amo.permissions.ADDONS_REVIEW):
            tabnav.append(
                (
                    'extension',
                    'queue_extension',
                    '🛠️ Manual Review',
                )
            )
            tabnav.append(
                (
                    'human_review',
                    'queue_human_review',
                    'Versions Needing Human Review',
                )
            )
            tabnav.append(('mad', 'queue_mad', 'Flagged by MAD for Human Review'))
        if acl.action_allowed_for(request.user, amo.permissions.STATIC_THEMES_REVIEW):
            tabnav.extend(
                (
                    (
                        'theme_nominated',
                        'queue_theme_nominated',
                        '🎨 New',
                    ),
                    (
                        'theme_pending',
                        'queue_theme_pending',
                        '🎨 Updates',
                    ),
                )
            )
        if acl.action_allowed_for(request.user, amo.permissions.RATINGS_MODERATE):
            tabnav.append(('moderated', 'queue_moderated', 'Rating Reviews'))

        if acl.action_allowed_for(request.user, amo.permissions.ADDONS_REVIEW):
            tabnav.append(('auto_approved', 'queue_auto_approved', 'Auto Approved'))

        if acl.action_allowed_for(request.user, amo.permissions.ADDONS_CONTENT_REVIEW):
            tabnav.append(('content_review', 'queue_content_review', 'Content Review'))

        if acl.action_allowed_for(request.user, amo.permissions.REVIEWS_ADMIN):
            tabnav.append(
                (
                    'pending_rejection',
                    'queue_pending_rejection',
                    'Pending Rejection',
                )
            )
    else:
        tabnav = [
            ('all', 'unlisted_queue_all', 'All Unlisted Add-ons'),
        ]

    return tabnav


@library.global_function
@library.render_with('reviewers/includes/files_view.html')
@jinja2.pass_context
def file_view(context, version):
    return new_context(
        {
            # We don't need the hashes in the template.
            'file': version.file,
            'amo': context.get('amo'),
            'addon': context.get('addon'),
            'latest_not_disabled_version': context.get('latest_not_disabled_version'),
            # This allows the template to call waffle.flag().
            'request': context.get('request'),
            'base_version_pk': context.get('base_version_pk'),
            'version': version,
        }
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
