from django.conf import settings

import olympia.core.logger

from olympia import amo
from olympia.amo.celery import task
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import send_mail
from olympia.zadmin.models import EmailPreviewTopic


log = olympia.core.logger.getLogger('z.task')


@task(rate_limit='3/s')
def admin_email(
    all_recipients,
    subject,
    body,
    preview_only=False,
    from_email=settings.DEFAULT_FROM_EMAIL,
    preview_topic='admin_email',
    **kw
):
    log.info(
        '[%s@%s] admin_email about %r'
        % (len(all_recipients), admin_email.rate_limit, subject)
    )
    if preview_only:
        send = EmailPreviewTopic(topic=preview_topic).send_mail
    else:
        send = send_mail
    for recipient in all_recipients:
        send(subject, body, recipient_list=[recipient], from_email=from_email)


def get_context(addon, version, job, results, fileob=None):
    result_links = (
        absolutify(
            reverse('devhub.bulk_compat_result', args=[addon.slug, r.pk])
        )
        for r in results
    )
    addon_name = addon.name
    if fileob and fileob.platform != amo.PLATFORM_ALL.id:
        addon_name = u'%s (%s)' % (addon_name, fileob.get_platform_display())
    return {
        'ADDON_NAME': addon_name,
        'ADDON_VERSION': version.version,
        'APPLICATION': str(job.application),
        'COMPAT_LINK': absolutify(
            reverse('devhub.versions.edit', args=[addon.pk, version.pk])
        ),
        'RESULT_LINKS': ' '.join(result_links),
        'VERSION': job.target_version.version,
    }


@task
def celery_error(**kw):
    """
    This task raises an exception from celery to test error logging and
    Sentry hookup.
    """
    log.info('about to raise an exception from celery')
    raise RuntimeError('this is an exception from celery')
