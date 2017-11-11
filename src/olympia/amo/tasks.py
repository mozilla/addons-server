import datetime

from django.core.mail import EmailMessage, EmailMultiAlternatives

import olympia.core.logger
from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.celery import task
from olympia.amo.utils import get_email_backend
from olympia.bandwagon.models import Collection


log = olympia.core.logger.getLogger('z.task')


@task
def send_email(recipient, subject, message, from_email=None,
               html_message=None, attachments=None, real_email=False,
               cc=None, headers=None, max_retries=3, reply_to=None,
               **kwargs):
    backend = EmailMultiAlternatives if html_message else EmailMessage
    connection = get_email_backend(real_email)

    result = backend(subject, message, from_email, to=recipient, cc=cc,
                     connection=connection, headers=headers,
                     attachments=attachments, reply_to=reply_to)

    if html_message:
        result.attach_alternative(html_message, 'text/html')
    try:
        result.send()
        return True
    except Exception as e:
        log.exception('send_mail() failed with error: %s, retrying' % e)
        return send_email.retry(exc=e, max_retries=max_retries)


@task
def set_modified_on_object(obj, **kw):
    """Sets modified on one object at a time."""
    try:
        log.info('Setting modified on object: %s, %s' %
                 (obj.__class__.__name__, obj.pk))
        obj.update(modified=datetime.datetime.now())
    except Exception, e:
        log.error('Failed to set modified on: %s, %s - %s' %
                  (obj.__class__.__name__, obj.pk, e))


@task
def delete_logs(items, **kw):
    log.info('[%s@%s] Deleting logs' % (len(items), delete_logs.rate_limit))
    ActivityLog.objects.filter(pk__in=items).exclude(
        action__in=amo.LOG_KEEP).delete()


@task
def delete_anonymous_collections(items, **kw):
    log.info('[%s@%s] Deleting anonymous collections' %
             (len(items), delete_anonymous_collections.rate_limit))
    Collection.objects.filter(type=amo.COLLECTION_ANONYMOUS,
                              pk__in=items).delete()
