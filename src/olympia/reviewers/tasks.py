from django.conf import settings
from django.utils.translation import override, ugettext

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog, CommentLog, VersionLog
from olympia.addons.models import Addon
from olympia.addons.tasks import (
    create_persona_preview_images, theme_checksum)
from olympia.amo.celery import task
from olympia.amo.decorators import write
from olympia.amo.storage_utils import copy_stored_file, move_stored_file
from olympia.amo.utils import LocalFileStorage, send_mail_jinja
from olympia.reviewers.models import AutoApprovalSummary
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.task')


@task
def add_commentlog(items, **kw):
    log.info('[%s@%s] Adding CommentLog starting with ActivityLog: %s' %
             (len(items), add_commentlog.rate_limit, items[0]))

    for al in ActivityLog.objects.filter(pk__in=items):
        # Delete existing entries:
        CommentLog.objects.filter(activity_log=al).delete()

        # Create a new entry:
        if 'comments' in al.details:
            CommentLog(comments=al.details['comments'], activity_log=al).save()


@task
def add_versionlog(items, **kw):
    log.info('[%s@%s] Adding VersionLog starting with ActivityLog: %s' %
             (len(items), add_versionlog.rate_limit, items[0]))

    for al in ActivityLog.objects.filter(pk__in=items):
        # Delete existing entries:
        VersionLog.objects.filter(activity_log=al).delete()

        for a in al.arguments:
            if isinstance(a, Version):
                vl = VersionLog(version=a, activity_log=al)
                vl.save()
                # We need to save it twice to backdate the created date.
                vl.created = al.created
                vl.save()


@task
def send_mail(cleaned_data, theme_lock):
    """
    Send emails out for respective review actions taken on themes.
    """
    with override('en-US'):  # Make sure the email is always sent in english.
        theme = cleaned_data['theme']
        action = cleaned_data['action']
        comment = cleaned_data['comment']
        reject_reason = cleaned_data['reject_reason']

        reason = None
        if reject_reason:
            reason = amo.THEME_REJECT_REASONS[reject_reason]
        elif action == amo.ACTION_DUPLICATE:
            reason = ugettext('Duplicate Submission')

        emails = set(theme.addon.authors.values_list('email', flat=True))
        context = {
            'theme': theme,
            'base_url': settings.SITE_URL,
            'reason': reason,
            'comment': comment
        }

        subject = None
        if action == amo.ACTION_APPROVE:
            subject = ugettext('Thanks for submitting your Theme')
            template = 'reviewers/themes/emails/approve.html'

        elif action in (amo.ACTION_REJECT, amo.ACTION_DUPLICATE):
            subject = ugettext('A problem with your Theme submission')
            template = 'reviewers/themes/emails/reject.html'

        elif action == amo.ACTION_FLAG:
            subject = ugettext('Theme submission flagged for review')
            template = 'reviewers/themes/emails/flag_reviewer.html'

            # Send the flagged email to themes email.
            emails = [settings.THEMES_EMAIL]

        elif action == amo.ACTION_MOREINFO:
            subject = ugettext('A question about your Theme submission')
            template = 'reviewers/themes/emails/moreinfo.html'
            context['reviewer_email'] = theme_lock.reviewer.email

        send_mail_jinja(subject, template, context,
                        recipient_list=emails,
                        from_email=settings.ADDONS_EMAIL,
                        headers={'Reply-To': settings.THEMES_EMAIL})


@task
@write
def approve_rereview(theme):
    """Replace original theme with pending theme on filesystem."""
    # If reuploaded theme, replace old theme design.
    storage = LocalFileStorage()
    rereview = theme.rereviewqueuetheme_set.all()
    reupload = rereview[0]

    if reupload.header_path != reupload.theme.header_path:
        create_persona_preview_images(
            src=reupload.header_path,
            full_dst=[
                reupload.theme.thumb_path,
                reupload.theme.icon_path],
            set_modified_on=reupload.theme.addon.serializable_reference())

        if not reupload.theme.is_new():
            # Legacy themes also need a preview_large.jpg.
            # Modern themes use preview.png for both thumb and preview so there
            # is no problem there.
            copy_stored_file(reupload.theme.thumb_path,
                             reupload.theme.preview_path, storage=storage)

        move_stored_file(
            reupload.header_path, reupload.theme.header_path, storage=storage)

    theme = reupload.theme
    rereview.delete()
    theme_checksum(theme)
    theme.addon.increment_theme_version_number()


@task
@write
def reject_rereview(theme):
    """Delete pending theme from filesystem."""
    storage = LocalFileStorage()
    rereview = theme.rereviewqueuetheme_set.all()
    reupload = rereview[0]

    storage.delete(reupload.header_path)
    rereview.delete()


@task
@write
def recalculate_post_review_weight(ids):
    """Recalculate the post-review weight that should be assigned to
    auto-approved add-on versions from a list of ids."""
    addons = Addon.objects.filter(id__in=ids)
    for addon in addons:
        summaries = AutoApprovalSummary.objects.filter(
            version__in=addon.versions.all())

        for summary in summaries:
            summary.calculate_weight()
            summary.save()
