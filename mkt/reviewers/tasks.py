import datetime
import logging

from django.conf import settings

from celeryutils import task
from tower import ugettext as _

import amo
from amo.utils import send_mail_jinja
import mkt.constants.reviewers as rvw


log = logging.getLogger('z.task')


@task
def send_mail(cleaned_data, theme_lock):
    """
    Send emails out for respective review actions taken on themes.
    """
    theme = cleaned_data['theme']
    action = cleaned_data['action']
    reject_reason = cleaned_data['reject_reason']
    reason = None
    if reject_reason:
        reason = rvw.THEME_REJECT_REASONS[reject_reason]
    elif action == rvw.ACTION_DUPLICATE:
        reason = _('Duplicate Submission')
    comment = cleaned_data['comment']

    emails = set(theme.addon.authors.values_list('email', flat=True))
    cc = settings.THEMES_EMAIL
    context = {
        'theme': theme,
        'base_url': settings.SITE_URL,
        'reason': reason,
        'comment': comment
    }

    subject = None
    if action == rvw.ACTION_APPROVE:
        subject = _('Thanks for submitting your Theme')
        template = 'reviewers/themes/emails/approve.html'
        theme.addon.update(status=amo.STATUS_PUBLIC)

    elif action == rvw.ACTION_REJECT:
        subject = _('A problem with your Theme submission')
        template = 'reviewers/themes/emails/reject.html'
        theme.addon.update(status=amo.STATUS_REJECTED)

    elif action == rvw.ACTION_DUPLICATE:
        subject = _('A problem with your Theme submission')
        template = 'reviewers/themes/emails/reject.html'
        theme.addon.update(status=amo.STATUS_REJECTED)

    elif action == rvw.ACTION_FLAG:
        subject = _('Theme submission flagged for review')
        template = 'reviewers/themes/emails/flag_reviewer.html'
        theme.addon.update(status=amo.STATUS_REVIEW_PENDING)

        # Send the flagged email to themes email.
        emails = [settings.THEMES_EMAIL]
        cc = None

    elif action == rvw.ACTION_MOREINFO:
        subject = _('A question about your Theme submission')
        template = 'reviewers/themes/emails/moreinfo.html'
        context['reviewer_email'] = theme_lock.reviewer.email
        theme.addon.update(status=amo.STATUS_REVIEW_PENDING)

    amo.log(amo.LOG.THEME_REVIEW, theme.addon, details={
            'action': action,
            'reject_reason': reject_reason,
            'comment': comment}, user=theme_lock.reviewer)
    log.info('Theme %s (%s) - %s' % (theme.addon.name, theme.id, action))

    theme.approve = datetime.datetime.now()
    theme.save()

    send_mail_jinja(subject, template, context,
                    recipient_list=emails, cc=cc,
                    from_email=settings.ADDONS_EMAIL,
                    headers={'Reply-To': settings.THEMES_EMAIL})
