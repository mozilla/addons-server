import datetime

import jinja2
from django_jinja import library

from olympia.access import acl
from olympia.amo.templatetags.jinja_helpers import new_context
from olympia.ratings.permissions import user_can_delete_rating
from olympia.reviewers.templatetags import assay, code_manager


@library.global_function
@jinja2.pass_context
def queue_tabnav(context, reviewer_tables_registry):
    """Returns tuple of tab navigation for the queue pages.

    Each tuple contains three elements: (tab_code, page_url, tab_text)
    """
    request = context['request']
    tabnav = []

    for queue in (
        'extension',
        'mad',
        'theme',
        'moderated',
        'content_review',
        'pending_rejection',
        'held_actions',
    ):
        if acl.action_allowed_for(
            request.user, reviewer_tables_registry[queue].permission
        ):
            tabnav.append(
                (
                    queue,
                    reviewer_tables_registry[queue].urlname,
                    reviewer_tables_registry[queue].title,
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
def assay_url(addon_guid, version_string, filepath=None):
    return assay.assay_url(addon_guid, version_string, filepath)


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


@library.filter
def to_dom_id(string):
    return string.replace('.', '_')
