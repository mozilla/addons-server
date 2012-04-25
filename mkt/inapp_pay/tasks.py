import calendar
import logging
import time
from urllib2 import urlopen
import urlparse

from django.conf import settings

from celeryutils import task
import jwt

import amo
from amo.decorators import write

from .models import InappPayment, InappPayNotice

log = logging.getLogger('z.inapp_pay.tasks')
task_kw = dict(default_retry_delay=15,  # seconds
               max_tries=5)


@task(**task_kw)
@write
def payment_notify(payment_id, **kw):
    """Notify the app of a successful payment.

    payment_id: pk of InappPayment
    """
    log.debug('sending payment notice for payment %s' % payment_id)
    _notify(payment_id, amo.INAPP_NOTICE_PAY, payment_notify)


@task(**task_kw)
@write
def chargeback_notify(payment_id, reason, **kw):
    """Notify the app of a chargeback.

    payment_id: pk of InappPayment
    reason: either 'reversal' or 'refund'
    """
    log.debug('sending chargeback notice for payment %s, reason %r'
              % (payment_id, reason))
    _notify(payment_id, amo.INAPP_NOTICE_CHARGEBACK,
            chargeback_notify,
            extra_response={'reason': reason})


def _notify(payment_id, notice_type, notifier_task, extra_response=None):
    payment = InappPayment.objects.get(pk=payment_id)
    config = payment.config
    contrib = payment.contribution
    response = {'transactionID': contrib.pk}
    if extra_response:
        response.update(extra_response)
    if notice_type == amo.INAPP_NOTICE_PAY:
        uri = config.postback_url
        typ = 'mozilla/payments/pay/postback/v1'
    elif notice_type == amo.INAPP_NOTICE_CHARGEBACK:
        uri = config.chargeback_url
        typ = 'mozilla/payments/pay/chargeback/v1'
    else:
        raise NotImplementedError('Unknown type: %s' % notice_type)
    url = urlparse.urlunparse((config.app_protocol(), config.addon.app_domain,
                               uri, '', '', ''))
    exception = None
    success = False
    issued_at = calendar.timegm(time.gmtime())

    signed_notice = jwt.encode({'iss': settings.INAPP_MARKET_ID,
                                'aud': config.public_key,  # app ID
                                'typ': typ,
                                'iat': issued_at,
                                'exp': issued_at + 3600,  # expires in 1 hour
                                'request': {'price': str(contrib.amount),
                                            'currency': contrib.currency,
                                            'name': payment.name,
                                            'description': payment.description,
                                            'productdata': payment.app_data},
                                'response': response},
                               config.get_private_key(),
                               algorithm='HS256')
    try:
        res = urlopen(url, signed_notice, timeout=5)
        res_content = res.read().strip()
    except AssertionError:
        raise  # Raise test-related exceptions.
    except Exception, exception:
        log.error('In-app payment %s raised exception in URL %s'
                  % (payment.pk, url), exc_info=True)
        try:
            notifier_task.retry(exc=exception)
        except:
            log.exception('retrying in-app payment %s notification URL %s'
                          % (payment.pk, url))
    else:
        if res_content == str(contrib.pk):
            success = True
            log.debug('app config %s responded OK for in-app payment %s'
                      % (config.pk, payment.pk))
        else:
            log.error('app config %s did not respond with contribution ID %s '
                      'for in-app payment %s' % (config.pk, contrib.pk,
                                                 payment.pk))
        res.close()

    if exception:
        last_error = u'%s: %s' % (exception.__class__.__name__, exception)
    else:
        last_error = ''
    s = InappPayNotice._meta.get_field_by_name('last_error')[0].max_length
    last_error = last_error[:s]  # truncate to fit

    InappPayNotice.objects.create(payment=payment,
                                  notice=notice_type,
                                  success=success,
                                  url=url,
                                  last_error=last_error)
