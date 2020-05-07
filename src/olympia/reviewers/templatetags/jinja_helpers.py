import datetime

from django.conf import settings
from django.utils.encoding import force_text
from django.utils.translation import ugettext, ungettext

import jinja2

from django_jinja import library

from olympia import amo
from olympia.access import acl
from olympia.addons.templatetags.jinja_helpers import new_context
from olympia.ratings.permissions import user_can_delete_rating
from olympia.reviewers.models import ReviewerScore
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
    return file.STATUS_CHOICES.get(
        file.status, ugettext('[status:%s]') % file.status)


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
    counts = context['queue_counts']
    request = context['request']
    listed = not context.get('unlisted')

    if listed:
        tabnav = []
        if acl.action_allowed(
                request, amo.permissions.ADDONS_RECOMMENDED_REVIEW):
            tabnav.append(
                ('recommended', 'queue_recommended',
                 ugettext('Recommended ({0})').format(counts['recommended'])),
            )
        if acl.action_allowed(request, amo.permissions.ADDONS_REVIEW):
            new_text = ugettext('Other Pending Review ({0})')
            tabnav.extend((
                ('extension', 'queue_extension',
                 '🛠️ ' + new_text.format(counts['extension'])),
            ))
            tabnav.append((
                'scanners',
                'queue_scanners',
                (ungettext(
                    'Flagged By Scanners ({0})',
                    'Flagged By Scanners ({0})',
                    counts['scanners']
                ) .format(counts['scanners'])),
            ))
            tabnav.append((
                'mad',
                'queue_mad',
                (ungettext(
                    'Flagged for Human Review ({0})',
                    'Flagged for Human Review ({0})',
                    counts['mad']
                ).format(counts['mad'])),
            ))
        if acl.action_allowed(request, amo.permissions.STATIC_THEMES_REVIEW):
            new_text = ugettext('New ({0})')
            update_text = ungettext(
                'Update ({0})', 'Updates ({0})', counts['theme_pending'])
            tabnav.extend((
                ('theme_nominated', 'queue_theme_nominated',
                 '🎨 ' + new_text.format(counts['theme_nominated'])),
                ('theme_pending', 'queue_theme_pending',
                 '🎨 ' + update_text.format(counts['theme_pending'])),
            ))
        if acl.action_allowed(request, amo.permissions.RATINGS_MODERATE):
            tabnav.append(
                ('moderated', 'queue_moderated',
                 (ungettext('Rating Review ({0})',
                            'Rating Reviews ({0})',
                            counts['moderated'])
                  .format(counts['moderated']))),
            )

        if acl.action_allowed(request, amo.permissions.ADDONS_POST_REVIEW):
            tabnav.append(
                ('auto_approved', 'queue_auto_approved',
                 (ungettext('Auto Approved ({0})',
                            'Auto Approved ({0})',
                            counts['auto_approved'])
                  .format(counts['auto_approved']))),
            )

        if acl.action_allowed(request, amo.permissions.ADDONS_CONTENT_REVIEW):
            tabnav.append(
                ('content_review', 'queue_content_review',
                 (ungettext('Content Review ({0})',
                            'Content Review ({0})',
                            counts['content_review'])
                  .format(counts['content_review']))),
            )

        if acl.action_allowed(request, amo.permissions.REVIEWS_ADMIN):
            tabnav.append(
                ('expired_info_requests', 'queue_expired_info_requests',
                 (ungettext('Expired Info Request ({0})',
                            'Expired Info Requests ({0})',
                            counts['expired_info_requests'])
                  .format(counts['expired_info_requests']))),
            )
    else:
        tabnav = [
            ('all', 'unlisted_queue_all', ugettext('All Unlisted Add-ons'))
        ]

    return tabnav


@library.global_function
@library.render_with('reviewers/includes/reviewers_score_bar.html')
@jinja2.contextfunction
def reviewers_score_bar(context, types=None, addon_type=None):
    user = context.get('user')

    return new_context(dict(
        request=context.get('request'),
        amo=amo, settings=settings,
        points=ReviewerScore.get_recent(user, addon_type=addon_type),
        total=ReviewerScore.get_total(user),
        **ReviewerScore.get_leaderboards(user, types=types,
                                         addon_type=addon_type)))


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
    return new_context(dict(
        # This allows the template to call static().
        BUILD_ID_IMG=context.get('BUILD_ID_IMG'),
        # We don't need the hashes in the template.
        distinct_files=hashes_to_file.values(),
        amo=context.get('amo'),
        addon=context.get('addon'),
        # This allows the template to call waffle.flag().
        request=context.get('request'),
        show_diff=context.get('show_diff'),
        version=version))


@library.global_function
def get_position(addon):
    if addon.status in amo.VALID_ADDON_STATUSES:
        # Look at all add-on versions which have files awaiting review.
        qs = Version.objects.filter(addon__disabled_by_user=False,
                                    files__status=amo.STATUS_AWAITING_REVIEW,
                                    addon__status=addon.status)
        if addon.type == amo.ADDON_STATICTHEME:
            qs = qs.filter(addon__type=amo.ADDON_STATICTHEME)
        else:
            qs = qs.exclude(addon__type=amo.ADDON_STATICTHEME)
        qs = (qs.order_by('nomination', 'created').distinct()
              .no_transforms().values_list('addon_id', flat=True))
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
def code_manager_url(path):
    if not path.startswith('/'):
        raise ValueError(
            'Expected a relative path; got: "{}"'.format(path)
        )
    # Always return URLs in en-US because the Code Manager is not localized.
    return '{}/en-US{}'.format(settings.CODE_MANAGER_URL, path)


@library.global_function
@jinja2.contextfunction
def check_review_delete(context, rating):
    return user_can_delete_rating(context['request'], rating)
