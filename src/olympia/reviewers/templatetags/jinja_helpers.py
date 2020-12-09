import datetime

from django.conf import settings
from django.utils.encoding import force_text
from django.utils.translation import ugettext

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
def file_compare(file_obj, version):
    # Compare this file to the one in the version with same platform
    file_obj = version.files.filter(platform=file_obj.platform)
    # If not there, just compare to all.
    if not file_obj:
        file_obj = version.files.filter(platform=amo.PLATFORM_ALL.id)
    # At this point we've got no idea what Platform file to
    # compare with, so just chose the first.
    if not file_obj:
        file_obj = version.files.all()
    return file_obj[0]


@library.global_function
def file_review_status(addon, file):
    if file.status == amo.STATUS_DISABLED:
        if file.reviewed is not None:
            return ugettext(u'Rejected')
        # Can't assume that if the reviewed date is missing its
        # unreviewed.  Especially for versions.
        else:
            return ugettext(u'Rejected or Unreviewed')
    return file.STATUS_CHOICES.get(file.status, ugettext('[status:%s]') % file.status)


@library.global_function
def version_status(addon, version):
    if version.deleted:
        return ugettext(u'Deleted')
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
            tabnav.append(('recommended', 'queue_recommended', ugettext('Recommended')))
        if acl.action_allowed(request, amo.permissions.ADDONS_REVIEW):
            tabnav.append(
                (
                    'extension',
                    'queue_extension',
                    '🛠️ ' + ugettext('Other Pending Review'),
                )
            )
            tabnav.append(
                ('scanners', 'queue_scanners', ugettext('Flagged By Scanners'))
            )
            tabnav.append(('mad', 'queue_mad', ugettext('Flagged for Human Review')))
        if acl.action_allowed(request, amo.permissions.STATIC_THEMES_REVIEW):
            tabnav.extend(
                (
                    (
                        'theme_nominated',
                        'queue_theme_nominated',
                        '🎨 ' + ugettext('New'),
                    ),
                    (
                        'theme_pending',
                        'queue_theme_pending',
                        '🎨 ' + ugettext('Updates'),
                    ),
                )
            )
        if acl.action_allowed(request, amo.permissions.RATINGS_MODERATE):
            tabnav.append(('moderated', 'queue_moderated', ugettext('Rating Reviews')))

        if acl.action_allowed(request, amo.permissions.ADDONS_REVIEW):
            tabnav.append(
                ('auto_approved', 'queue_auto_approved', ugettext('Auto Approved'))
            )

        if acl.action_allowed(request, amo.permissions.ADDONS_CONTENT_REVIEW):
            tabnav.append(
                ('content_review', 'queue_content_review', ugettext('Content Review'))
            )

        if acl.action_allowed(request, amo.permissions.REVIEWS_ADMIN):
            tabnav.append(
                (
                    'pending_rejection',
                    'queue_pending_rejection',
                    ugettext('Pending Rejection'),
                )
            )
    else:
        tabnav = [('all', 'unlisted_queue_all', ugettext('All Unlisted Add-ons'))]

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
def all_distinct_files(context, version):
    """Only display a file once even if it's been uploaded
    for several platforms."""
    # hashes_to_file will group files per hash:
    # {<file.hash>: [<file>, 'Windows / Mac OS X']}
    hashes_to_file = {}
    for file_ in version.all_files:
        display_name = force_text(amo.PLATFORMS[file_.platform].name)
        if file_.original_hash in hashes_to_file:
            hashes_to_file[file_.original_hash][1] += ' / ' + display_name
        else:
            hashes_to_file[file_.original_hash] = [file_, display_name]
    return new_context(
        dict(
            # This allows the template to call static().
            BUILD_ID_IMG=context.get('BUILD_ID_IMG'),
            # We don't need the hashes in the template.
            distinct_files=hashes_to_file.values(),
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
