import datetime

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.utils import translation

import requests

from waffle import switch_is_active

import olympia.core.logger

from olympia import amo
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import get_email_backend
from olympia.bandwagon.models import Collection
from olympia.lib.akismet.models import AkismetReport


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
def set_modified_on_object(app_label, model_name, pk, **kw):
    """Sets modified on one object at a time."""
    model = apps.get_model(app_label, model_name)
    obj = model.objects.get(pk=pk)
    try:
        log.info('Setting modified on object: %s, %s' % (model_name, pk))
        obj.update(modified=datetime.datetime.now(), **kw)
    except Exception as e:
        log.error('Failed to set modified on: %s, %s - %s' %
                  (model_name, pk, e))


@task
def delete_logs(items, **kw):
    from olympia.activity.models import ActivityLog
    log.info('[%s@%s] Deleting logs' % (len(items), delete_logs.rate_limit))
    ActivityLog.objects.filter(pk__in=items).exclude(
        action__in=amo.LOG_KEEP).delete()


@task
def delete_akismet_reports(items, **kw):
    log.info('[%s@%s] Deleting akismet reports' %
             (len(items), delete_akismet_reports.rate_limit))
    AkismetReport.objects.filter(pk__in=items).delete()


@task
def delete_anonymous_collections(items, **kw):
    log.info('[%s@%s] Deleting anonymous collections' %
             (len(items), delete_anonymous_collections.rate_limit))
    Collection.objects.filter(type=amo.COLLECTION_ANONYMOUS,
                              pk__in=items).delete()


@task
@use_primary_db
def sync_object_to_basket(model_name, pk):
    """
    Celery task to sync an object (UserProfile or Addon instance) with Basket.
    """
    if not switch_is_active('basket-amo-sync'):
        log.info(
            'Not synchronizing %s %s with basket because "basket-amo-sync" '
            'switch is off.', model_name, pk)
        return
    else:
        log.info('Synchronizing %s %s with basket.', model_name, pk)
    from olympia.accounts.serializers import UserProfileBasketSyncSerializer
    from olympia.addons.serializers import AddonBasketSyncSerializer

    # Note: whenever a AddonUser changes, we'll be sent the Addon to sync.
    # That will include all known authors (make sure we're de-duping the
    # calls correctly, in theory that should be handled by post-request-task).

    serializers = {
        'addon': AddonBasketSyncSerializer,
        'userprofile': UserProfileBasketSyncSerializer,
    }
    serializer_class = serializers.get(model_name)
    if not serializer_class:
        raise ImproperlyConfigured(
            'No serializer found to synchronise that model name with basket')
    model = serializer_class.Meta.model
    manager = getattr(model, 'unfiltered', model.objects)
    try:
        obj = manager.get(pk=pk)
    except model.DoesNotExist:
        log.exception(
            'Not synchronizing %s %s with basket because it does not exist',
            model_name, pk)
        return
    locale_to_use = getattr(obj, 'default_locale', settings.LANGUAGE_CODE)
    with translation.override(locale_to_use):
        serializer = serializer_class(obj)
        data = serializer.data

    basket_endpoint = f'{settings.BASKET_URL}/amo-sync/{model_name}/'
    response = requests.post(
        basket_endpoint, json=data, timeout=settings.BASKET_TIMEOUT,
        headers={'x-api-key': settings.BASKET_API_KEY or ''})
    # Explicitly raise for errors so that we see them in Sentry.
    response.raise_for_status()
