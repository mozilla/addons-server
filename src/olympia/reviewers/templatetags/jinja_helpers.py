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
from olympia.versions.models import Version


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
    return ','.join(str(s) for s in version.status)


@library.global_function
@jinja2.contextfunction
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
@jinja2.contextfunction
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
@jinja2.contextfunction
def all_files(context, version):
    return new_context(
        dict(
            # This allows the template to call static().
            BUILD_ID_IMG=context.get('BUILD_ID_IMG'),
            # We don't need the hashes in the template.
            all_files=version.all_files,
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
def get_position(addon):
    if addon.status in amo.VALID_ADDON_STATUSES:
        # Look at all add-on versions which have files awaiting review.
        qs = Version.objects.filter(
            addon__disabled_by_user=False,
            files__status=amo.STATUS_AWAITING_REVIEW,
            addon__status=addon.status,
        )
        if addon.type == amo.ADDON_STATICTHEME:
            qs = qs.filter(addon__type=amo.ADDON_STATICTHEME)
        else:
            qs = qs.exclude(addon__type=amo.ADDON_STATICTHEME)
        qs = (
            qs.order_by('nomination', 'created')
            .distinct()
            .no_transforms()
            .values_list('addon_id', flat=True)
        )
        position = 0
        for idx, addon_id in enumerate(qs, start=1):
            if addon_id == addon.id:
                position = idx
                break
        total = qs.count()
        if position:
            return {'pos': position, 'total': total}

    return False


@library.global_function
@jinja2.contextfunction
def is_expired_lock(context, lock):
    return lock.expiry < datetime.datetime.now()


@library.global_function
def code_manager_url(page, addon_id, version_id, base_version_id=None):
    return code_manager.code_manager_url(page, addon_id, version_id, base_version_id)


@library.global_function
@jinja2.contextfunction
def check_review_delete(context, rating):
    return user_can_delete_rating(context['request'], rating)


@library.filter
def format_score(value):
    return '{:0.0f}%'.format(value) if value and value >= 0 else 'n/a'
