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
def queue_tabnav(context, reviewer_tables_registry):
    """Returns tuple of tab navigation for the queue pages.

    Each tuple contains three elements: (tab_code, page_url, tab_text)
    """
    request = context['request']
    tabnav = []

    if acl.action_allowed_for(request.user, amo.permissions.ADDONS_REVIEW):
        tabnav.extend(
            (
                (
                    'extension',
                    reviewer_tables_registry['extension'].urlname,
                    reviewer_tables_registry['extension'].title,
                ),
                (
                    'mad',
                    reviewer_tables_registry['mad'].urlname,
                    reviewer_tables_registry['mad'].title,
                ),
            )
        )
    if acl.action_allowed_for(request.user, amo.permissions.STATIC_THEMES_REVIEW):
        tabnav.extend(
            (
                (
                    'theme_nominated',
                    reviewer_tables_registry['theme_nominated'].urlname,
                    reviewer_tables_registry['theme_nominated'].title,
                ),
                (
                    'theme_pending',
                    reviewer_tables_registry['theme_pending'].urlname,
                    reviewer_tables_registry['theme_pending'].title,
                ),
            )
        )
    if acl.action_allowed_for(request.user, amo.permissions.RATINGS_MODERATE):
        tabnav.append(('moderated', 'queue_moderated', 'Rating Reviews'))

    if acl.action_allowed_for(request.user, amo.permissions.ADDONS_CONTENT_REVIEW):
        tabnav.append(
            (
                'content_review',
                reviewer_tables_registry['content_review'].urlname,
                reviewer_tables_registry['content_review'].title,
            )
        )

    if acl.action_allowed_for(request.user, amo.permissions.REVIEWS_ADMIN):
        tabnav.append(
            (
                'pending_rejection',
                reviewer_tables_registry['pending_rejection'].urlname,
                reviewer_tables_registry['pending_rejection'].title,
            )
        )

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
